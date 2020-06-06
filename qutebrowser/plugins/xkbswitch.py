# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

from ctypes import CDLL, c_char_p
from PyQt5.QtCore import pyqtSlot, QObject
from qutebrowser.utils.usertypes import KeyMode


class XkbSwitchPlugin(QObject):

    def __init__(self, *, win_id, parent=None):
        super().__init__(parent)
        self.xkb_enabled = True
        try:
            self._xkb_lib = CDLL('/usr/lib/libxkbswitch.so')

            self._xget = self._xkb_lib.Xkb_Switch_getXkbLayout
            self._xget.restype = c_char_p
            self._xget.argtypes = c_char_p,

            self._xset = self._xkb_lib.Xkb_Switch_setXkbLayout
            self._xset.restype = c_char_p
            self._xset.argtypes = c_char_p,

            self._nlayout = b'us'
            self._ilayout = b'us'

        except:
            self.xkb_enabled = False


    def _swap_layouts(self):
        if not self.xkb_enabled:
            return
        temp = self._xget(None)
        self._xset(self._layout)
        self._layout = temp

    def _push_layout(self, layout):
        if not self.xkb_enabled:
            return
        temp = self._xget(None)
        self._xset(layout)
        return temp

    @pyqtSlot(KeyMode)
    def on_mode_entered(self, mode):
        """Trigger switch on entering input mode."""
        if not self.xkb_enabled:
            return
        if mode == KeyMode.insert or mode == KeyMode.passthrough:
            self._push_layout(self._ilayout)

    @pyqtSlot(KeyMode, KeyMode)
    def on_mode_left(self, old_mode, new_mode):
        """Trigger restore on leaving input mode."""
        if not self.xkb_enabled:
            return
        if old_mode == KeyMode.insert or old_mode == KeyMode.passthrough:
            self._ilayout = self._push_layout(self._nlayout)

