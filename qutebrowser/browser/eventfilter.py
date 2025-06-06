# SPDX-FileCopyrightText: Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Event handling for a browser tab."""

from qutebrowser.qt import machinery
from qutebrowser.qt.core import QObject, QEvent, Qt, QTimer
from qutebrowser.qt.gui import QKeyEvent
from qutebrowser.qt.widgets import QWidget

from qutebrowser.config import config
from qutebrowser.utils import log, message, usertypes, qtutils
from qutebrowser.keyinput import modeman, keyutils


class ChildEventFilter(QObject):

    """An event filter re-adding TabEventFilter on ChildEvent.

    This is needed because QtWebEngine likes to randomly change its
    focusProxy...

    FIXME:qtwebengine Add a test for this happening

    Attributes:
        _filter: The event filter to install.
        _widget: The widget expected to send out childEvents.
    """

    def __init__(self, *, eventfilter, widget=None, parent=None):
        super().__init__(parent)
        self._filter = eventfilter
        self._widget = widget

    def eventFilter(self, obj, event):
        """Act on ChildAdded events."""
        if event.type() == QEvent.Type.ChildAdded:
            child = event.child()
            if not isinstance(child, QWidget):
                # Can e.g. happen when dragging text, or accessibility tree
                # nodes since Qt 6.9
                return False

            log.misc.debug(
                f"{qtutils.qobj_repr(obj)} got new child {qtutils.qobj_repr(child)}, "
                "installing filter")

            # Additional sanity check, but optional
            if self._widget is not None:
                assert obj is self._widget

                # WORKAROUND for unknown Qt bug losing focus on child change
                # Carry on keyboard focus to the new child if:
                # - This is a child event filter on a tab (self._widget is not None)
                # - We find an old existing child which is a QQuickWidget and is
                #   currently focused.
                # - We're using QtWebEngine >= 6.4 (older versions are not affected)
                children = [
                    c for c in self._widget.findChildren(
                        QWidget, "", Qt.FindChildOption.FindDirectChildrenOnly)
                    if c is not child and
                    c.hasFocus() and
                    c.metaObject() is not None and
                    c.metaObject().className() == "QQuickWidget"
                ]
                if children:
                    log.misc.debug("Focusing new child")
                    child.setFocus()

            child.installEventFilter(self._filter)
        elif event.type() == QEvent.Type.ChildRemoved:
            if isinstance(event, QKeyEvent):
                # WORKAROUND for unknown (Py)Qt bug
                info = keyutils.KeyInfo.from_event(event)
                log.misc.warning(
                    f"ChildEventFilter: ignoring key event {info} "
                    f"on {qtutils.qobj_repr(obj)}"
                )
                return False

            child = event.child()
            log.misc.debug(
                f"{qtutils.qobj_repr(obj)}: removed child {qtutils.qobj_repr(child)}")

        return False


class TabEventFilter(QObject):

    """Handle mouse/keyboard events on a tab.

    Attributes:
        _tab: The browsertab object this filter is installed on.
        _handlers: A dict of handler functions for the handled events.
        _ignore_wheel_event: Whether to ignore the next wheelEvent.
        _check_insertmode_on_release: Whether an insertmode check should be
                                      done when the mouse is released.
    """

    def __init__(self, tab, *, parent=None):
        super().__init__(parent)
        self._tab = tab
        self._handlers = {
            QEvent.Type.MouseButtonPress: self._handle_mouse_press,
            QEvent.Type.MouseButtonRelease: self._handle_mouse_release,
            QEvent.Type.Wheel: self._handle_wheel,
        }
        self._ignore_wheel_event = False
        self._check_insertmode_on_release = False

    def _handle_mouse_press(self, e):
        """Handle pressing of a mouse button.

        Args:
            e: The QMouseEvent.

        Return:
            True if the event should be filtered, False otherwise.
        """
        is_rocker_gesture = (config.val.input.mouse.rocker_gestures and
                             e.buttons() == Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)

        if e.button() in [Qt.MouseButton.XButton1, Qt.MouseButton.XButton2] or is_rocker_gesture:
            if not machinery.IS_QT6:
                self._mousepress_backforward(e)
            # FIXME:qt6 For some reason, this doesn't filter the action on
            # Qt 6...
            return True

        self._ignore_wheel_event = True

        pos = e.pos()
        if pos.x() < 0 or pos.y() < 0:
            log.mouse.warning("Ignoring invalid click at {}".format(pos))
            return False

        if e.button() != Qt.MouseButton.NoButton:
            self._tab.elements.find_at_pos(pos, self._mousepress_insertmode_cb)

        return False

    def _handle_mouse_release(self, _e):
        """Handle releasing of a mouse button.

        Args:
            e: The QMouseEvent.

        Return:
            True if the event should be filtered, False otherwise.
        """
        # We want to make sure we check the focus element after the WebView is
        # updated completely.
        QTimer.singleShot(0, self._mouserelease_insertmode)
        return False

    def _handle_wheel(self, e):
        """Zoom on Ctrl-Mousewheel.

        Args:
            e: The QWheelEvent.

        Return:
            True if the event should be filtered, False otherwise.
        """
        if self._ignore_wheel_event:
            # See https://github.com/qutebrowser/qutebrowser/issues/395
            self._ignore_wheel_event = False
            return True

        # Don't allow scrolling while hinting
        mode = modeman.instance(self._tab.win_id).mode
        if mode == usertypes.KeyMode.hint:
            return True

        elif e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if mode == usertypes.KeyMode.passthrough:
                return False

            divider = config.val.zoom.mouse_divider
            if divider == 0:
                # Disable mouse zooming
                return True

            factor = self._tab.zoom.factor() + (e.angleDelta().y() / divider)
            if factor < 0:
                return True

            perc = int(100 * factor)
            message.info(f"Zoom level: {perc}%", replace='zoom-level')
            self._tab.zoom.set_factor(factor)
            return True

        return False

    def _mousepress_insertmode_cb(self, elem):
        """Check if the clicked element is editable."""
        if elem is None:
            # Something didn't work out, let's find the focus element after
            # a mouse release.
            log.mouse.debug("Got None element, scheduling check on "
                            "mouse release")
            self._check_insertmode_on_release = True
            return

        if elem.is_editable():
            log.mouse.debug("Clicked editable element!")
            if config.val.input.insert_mode.auto_enter:
                modeman.enter(self._tab.win_id, usertypes.KeyMode.insert,
                              'click', only_if_normal=True)
        else:
            log.mouse.debug("Clicked non-editable element!")
            if config.val.input.insert_mode.auto_leave:
                modeman.leave(self._tab.win_id, usertypes.KeyMode.insert,
                              'click', maybe=True)

    def _mouserelease_insertmode(self):
        """If we have an insertmode check scheduled, handle it."""
        if not self._check_insertmode_on_release:
            return
        self._check_insertmode_on_release = False

        def mouserelease_insertmode_cb(elem):
            """Callback which gets called from JS."""
            if elem is None:
                log.mouse.debug("Element vanished!")
                return

            if elem.is_editable():
                log.mouse.debug("Clicked editable element (delayed)!")
                modeman.enter(self._tab.win_id, usertypes.KeyMode.insert,
                              'click-delayed', only_if_normal=True)
            else:
                log.mouse.debug("Clicked non-editable element (delayed)!")
                if config.val.input.insert_mode.auto_leave:
                    modeman.leave(self._tab.win_id, usertypes.KeyMode.insert,
                                  'click-delayed', maybe=True)

        self._tab.elements.find_focused(mouserelease_insertmode_cb)

    def _mousepress_backforward(self, e):
        """Handle back/forward mouse button presses.

        Args:
            e: The QMouseEvent.

        Return:
            True if the event should be filtered, False otherwise.
        """
        if (not config.val.input.mouse.back_forward_buttons and
                e.button() in [Qt.MouseButton.XButton1, Qt.MouseButton.XButton2]):
            # Back and forward on mice are disabled
            return

        if e.button() in [Qt.MouseButton.XButton1, Qt.MouseButton.LeftButton]:
            # Back button on mice which have it, or rocker gesture
            if self._tab.history.can_go_back():
                self._tab.history.back()
            else:
                message.error("At beginning of history.")
        elif e.button() in [Qt.MouseButton.XButton2, Qt.MouseButton.RightButton]:
            # Forward button on mice which have it, or rocker gesture
            if self._tab.history.can_go_forward():
                self._tab.history.forward()
            else:
                message.error("At end of history.")

    def eventFilter(self, obj, event):
        """Filter events going to a QWeb(Engine)View.

        Return:
            True if the event should be filtered, False otherwise.
        """
        evtype = event.type()
        if evtype not in self._handlers:
            return False
        if obj is not self._tab.private_api.event_target():
            log.mouse.debug("Ignoring {} to {}".format(
                event.__class__.__name__, obj))
            return False
        return self._handlers[evtype](event)
