# SPDX-FileCopyrightText: Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Get arguments to pass to Qt."""

import os
import sys
import argparse
import pathlib
# Using deprecated typing.Callable as a WORKAROUND because
# collections.abc.Callable inside Optional[...]/Union[...]
# is broken on Python 3.9.0 and 3.9.1
from typing import Any, Optional, Union, Callable
from collections.abc import Iterator, Sequence

from qutebrowser.qt import machinery
from qutebrowser.qt.core import QLocale

from qutebrowser.config import config
from qutebrowser.misc import objects
from qutebrowser.utils import usertypes, qtutils, utils, log, version


_ENABLE_FEATURES = '--enable-features='
_DISABLE_FEATURES = '--disable-features='
_BLINK_SETTINGS = '--blink-settings='


def qt_args(namespace: argparse.Namespace) -> list[str]:
    """Get the Qt QApplication arguments based on an argparse namespace.

    Args:
        namespace: The argparse namespace.

    Return:
        The argv list to be passed to Qt.
    """
    argv = [sys.argv[0]]

    if namespace.qt_flag is not None:
        argv += ['--' + flag[0] for flag in namespace.qt_flag]

    if namespace.qt_arg is not None:
        for name, value in namespace.qt_arg:
            argv += ['--' + name, value]

    argv += ['--' + arg for arg in config.val.qt.args]

    if objects.backend != usertypes.Backend.QtWebEngine:
        assert objects.backend == usertypes.Backend.QtWebKit, objects.backend
        return argv

    try:
        # pylint: disable=unused-import
        from qutebrowser.browser.webengine import webenginesettings
    except ImportError:
        # This code runs before a QApplication is available, so before
        # backendproblem.py is run to actually inform the user of the missing
        # backend. Thus, we could end up in a situation where we're here, but
        # QtWebEngine isn't actually available.
        # We shouldn't call _qtwebengine_args() in this case as it relies on
        # QtWebEngine actually being importable, e.g. in
        # version.qtwebengine_versions().
        log.init.debug("QtWebEngine requested, but unavailable...")
        return argv

    versions = version.qtwebengine_versions(avoid_init=True)
    if versions.webengine >= utils.VersionNumber(6, 4):
        # https://codereview.qt-project.org/c/qt/qtwebengine/+/376704
        argv.insert(1, "--webEngineArgs")

    special_prefixes = (_ENABLE_FEATURES, _DISABLE_FEATURES, _BLINK_SETTINGS)
    special_flags = [flag for flag in argv if flag.startswith(special_prefixes)]
    argv = [flag for flag in argv if not flag.startswith(special_prefixes)]
    argv += list(_qtwebengine_args(versions, namespace, special_flags))

    return argv


def _qtwebengine_features(  # noqa: C901
        versions: version.WebEngineVersions,
        special_flags: Sequence[str],
) -> tuple[Sequence[str], Sequence[str]]:
    """Get a tuple of --enable-features/--disable-features flags for QtWebEngine.

    Args:
        versions: The WebEngineVersions to get flags for.
        special_flags: Existing flags passed via the commandline.
    """
    assert versions.chromium_major is not None

    enabled_features = []
    disabled_features = []

    for flag in special_flags:
        if flag.startswith(_ENABLE_FEATURES):
            flag = flag.removeprefix(_ENABLE_FEATURES)
            enabled_features += flag.split(',')
        elif flag.startswith(_DISABLE_FEATURES):
            flag = flag.removeprefix(_DISABLE_FEATURES)
            disabled_features += flag.split(',')
        elif flag.startswith(_BLINK_SETTINGS):
            pass
        else:
            raise utils.Unreachable(flag)

    if utils.is_linux:
        # Enable WebRTC PipeWire for screen capturing on Wayland.
        #
        # This is disabled in Chromium by default because of the "dialog hell":
        # https://bugs.chromium.org/p/chromium/issues/detail?id=682122#c50
        # https://github.com/flatpak/xdg-desktop-portal-gtk/issues/204
        #
        # However, we don't have Chromium's confirmation dialog in qutebrowser,
        # so we should only get qutebrowser's permission dialog.
        #
        # In theory this would be supported with Qt 5.15.0 already, but
        # QtWebEngine only started picking up PipeWire correctly with Qt
        # 5.15.1.
        #
        # This only should be enabled on Wayland, but it's too early to check
        # that, as we don't have a QApplication available at this point. Thus,
        # just turn it on unconditionally on Linux, which shouldn't hurt.
        enabled_features.append('WebRTCPipeWireCapturer')

    if not utils.is_mac:
        # Enable overlay scrollbars.
        #
        # There are two additional flags in Chromium:
        #
        # - OverlayScrollbarFlashAfterAnyScrollUpdate
        # - OverlayScrollbarFlashWhenMouseEnter
        #
        # We don't expose/activate those, but the changes they introduce are
        # quite subtle: The former seems to show the scrollbar handle even if
        # there was a 0px scroll (though no idea how that can happen...). The
        # latter flashes *all* scrollbars when a scrollable area was entered,
        # which doesn't seem to make much sense.
        if config.val.scrolling.bar == 'overlay':
            enabled_features.append('OverlayScrollbar')

    if (config.val.content.headers.referer == 'same-domain' and
            versions.chromium_major < 89):
        # Handling of reduced-referrer-granularity in Chromium 76+
        # https://chromium-review.googlesource.com/c/chromium/src/+/1572699
        #
        # Note that this is removed entirely (and apparently the default) starting with
        # Chromium 89 (presumably arriving with Qt 6.2):
        # https://chromium-review.googlesource.com/c/chromium/src/+/2545444
        enabled_features.append('ReducedReferrerGranularity')

    if versions.webengine == utils.VersionNumber(5, 15, 2):
        # WORKAROUND for https://bugreports.qt.io/browse/QTBUG-89740
        disabled_features.append('InstalledApp')

    if versions.webengine >= utils.VersionNumber(6, 7):
        # WORKAROUND for https://bugreports.qt.io/browse/QTBUG-132681
        # TODO adjust if fixed in Qt 6.9.2+
        disabled_features.append('DocumentPictureInPictureAPI')

    if versions.webengine >= utils.VersionNumber(6, 9):
        # WORKAROUND for https://bugreports.qt.io/browse/QTBUG-135787
        # TODO adjust if fixed in Qt 6.9.2+
        disabled_features.append('PermissionElement')

    if not config.val.input.media_keys:
        disabled_features.append('HardwareMediaKeyHandling')

    return (enabled_features, disabled_features)


def _get_locale_pak_path(locales_path: pathlib.Path, locale_name: str) -> pathlib.Path:
    """Get the path for a locale .pak file."""
    return locales_path / (locale_name + '.pak')


def _get_pak_name(locale_name: str) -> str:
    """Get the Chromium .pak name for a locale name.

    Based on Chromium's behavior in l10n_util::CheckAndResolveLocale:
    https://source.chromium.org/chromium/chromium/src/+/master:ui/base/l10n/l10n_util.cc;l=344-428;drc=43d5378f7f363dab9271ca37774c71176c9e7b69
    """
    if locale_name in {'en', 'en-POSIX', 'en-PH', 'en-LR'}:
        return 'en-US'
    elif locale_name.startswith('en-'):
        return 'en-GB'
    elif locale_name.startswith('es-'):
        return 'es-419'
    elif locale_name == 'pt':
        return 'pt-BR'
    elif locale_name.startswith('pt-'):  # pragma: no cover
        return 'pt-PT'
    elif locale_name in {'zh-HK', 'zh-MO'}:
        return 'zh-TW'
    elif locale_name == 'zh' or locale_name.startswith('zh-'):
        return 'zh-CN'

    return locale_name.split('-')[0]


def _webengine_locales_path() -> pathlib.Path:
    """Get the path of the QtWebEngine locales."""
    if version.is_flatpak():
        # TranslationsPath is /usr/translations on Flatpak, i.e. the path for qtbase,
        # not QtWebEngine.
        base = pathlib.Path('/app/translations')
    else:
        base = qtutils.library_path(qtutils.LibraryPath.translations)
    return base / 'qtwebengine_locales'


def _get_lang_override(
        webengine_version: utils.VersionNumber,
        locale_name: str
) -> Optional[str]:
    """Get a --lang switch to override Qt's locale handling.

    This is needed as a WORKAROUND for https://bugreports.qt.io/browse/QTBUG-91715
    Fixed with QtWebEngine 5.15.4.
    """
    if not config.val.qt.workarounds.locale:
        return None

    if webengine_version != utils.VersionNumber(5, 15, 3) or not utils.is_linux:
        return None

    locales_path = _webengine_locales_path()
    if not locales_path.exists():
        log.init.debug(f"{locales_path} not found, skipping workaround!")
        return None

    pak_path = _get_locale_pak_path(locales_path, locale_name)
    if pak_path.exists():
        log.init.debug(f"Found {pak_path}, skipping workaround")
        return None

    pak_name = _get_pak_name(locale_name)
    pak_path = _get_locale_pak_path(locales_path, pak_name)
    if pak_path.exists():
        log.init.debug(f"Found {pak_path}, applying workaround")
        return pak_name

    log.init.debug(f"Can't find pak in {locales_path} for {locale_name} or {pak_name}")
    return 'en-US'


def _qtwebengine_args(
        versions: version.WebEngineVersions,
        namespace: argparse.Namespace,
        special_flags: Sequence[str],
) -> Iterator[str]:
    """Get the QtWebEngine arguments to use based on the config."""
    # https://codereview.qt-project.org/c/qt/qtwebengine/+/256786
    # https://codereview.qt-project.org/c/qt/qtwebengine-chromium/+/265753
    if 'stack' in namespace.debug_flags:
        yield '--enable-in-process-stack-traces'

    lang_override = _get_lang_override(
        webengine_version=versions.webengine,
        locale_name=QLocale().bcp47Name(),
    )
    if lang_override is not None:
        yield f'--lang={lang_override}'

    if 'chromium' in namespace.debug_flags:
        yield '--enable-logging'
        yield '--v=1'

    if 'wait-renderer-process' in namespace.debug_flags:
        yield '--renderer-startup-dialog'

    from qutebrowser.browser.webengine import darkmode
    darkmode_settings = darkmode.settings(
        versions=versions,
        special_flags=special_flags,
    )
    for switch_name, values in darkmode_settings.items():
        # If we need to use other switches (say, --enable-features), we might need to
        # refactor this so values still get combined with existing ones.
        assert switch_name in ['dark-mode-settings', 'blink-settings'], switch_name
        yield f'--{switch_name}=' + ','.join(f'{k}={v}' for k, v in values)

    enabled_features, disabled_features = _qtwebengine_features(versions, special_flags)
    if enabled_features:
        yield _ENABLE_FEATURES + ','.join(enabled_features)
    if disabled_features:
        yield _DISABLE_FEATURES + ','.join(disabled_features)

    yield from _qtwebengine_settings_args(versions)


_SettingValueType = Union[
    str,
    Callable[
        [
            version.WebEngineVersions,
        ],
        Optional[str],
    ],
]
_WEBENGINE_SETTINGS: dict[str, dict[Any, Optional[_SettingValueType]]] = {
    'qt.force_software_rendering': {
        'software-opengl': None,
        'qt-quick': None,
        'chromium': '--disable-gpu',
        'none': None,
    },
    'content.canvas_reading': {
        True: None,
        # might be overridden in webenginesettings.py
        False: '--disable-reading-from-canvas',
    },
    'content.webrtc_ip_handling_policy': {
        'all-interfaces': None,
        'default-public-and-private-interfaces':
            '--force-webrtc-ip-handling-policy='
            'default_public_and_private_interfaces',
        'default-public-interface-only':
            '--force-webrtc-ip-handling-policy='
            'default_public_interface_only',
        'disable-non-proxied-udp':
            '--force-webrtc-ip-handling-policy='
            'disable_non_proxied_udp',
    },
    'content.javascript.legacy_touch_events': {
        'always': '--touch-events=enabled',
        'auto': '--touch-events=auto',
        'never': '--touch-events=disabled',
    },
    'qt.chromium.process_model': {
        'process-per-site-instance': None,
        'process-per-site': '--process-per-site',
        'single-process': '--single-process',
    },
    'qt.chromium.low_end_device_mode': {
        'auto': None,
        'always': '--enable-low-end-device-mode',
        'never': '--disable-low-end-device-mode',
    },
    'content.prefers_reduced_motion': {
        True: '--force-prefers-reduced-motion',
        False: None,
    },
    'qt.chromium.sandboxing': {
        'enable-all': None,
        'disable-seccomp-bpf': '--disable-seccomp-filter-sandbox',
        'disable-all': '--no-sandbox',
    },
    'qt.chromium.experimental_web_platform_features': {
        'always': '--enable-experimental-web-platform-features',
        'never': None,
        'auto':
            '--enable-experimental-web-platform-features' if machinery.IS_QT5 else None,
    },
    'qt.workarounds.disable_accelerated_2d_canvas': {
        'always': '--disable-accelerated-2d-canvas',
        'never': None,
        'auto': lambda _versions: '--disable-accelerated-2d-canvas' if machinery.IS_QT6 else None,
    },
}


def _qtwebengine_settings_args(versions: version.WebEngineVersions) -> Iterator[str]:
    for setting, args in sorted(_WEBENGINE_SETTINGS.items()):
        arg = args[config.instance.get(setting)]
        if callable(arg):
            result = arg(versions)
            if result is not None:
                assert isinstance(
                    result, str
                ), f"qt.settings feature detection returned an invalid type: {type(result)} for {setting}"
                yield result
        elif arg is not None:
            yield arg


def _warn_qtwe_flags_envvar() -> None:
    """Warn about the QTWEBENGINE_CHROMIUM_FLAGS envvar if it is set."""
    qtwe_flags_var = 'QTWEBENGINE_CHROMIUM_FLAGS'
    qtwe_flags = os.environ.get(qtwe_flags_var)
    if qtwe_flags is not None:
        log.init.warning(
            f"You have {qtwe_flags_var}={qtwe_flags!r} set in your environment. "
            "This is currently unsupported and interferes with qutebrowser's own "
            "flag handling (including workarounds for certain crashes). "
            "Consider using the qt.args qutebrowser setting instead.")


def init_envvars() -> None:
    """Initialize environment variables which need to be set early."""
    if objects.backend == usertypes.Backend.QtWebEngine:
        software_rendering = config.val.qt.force_software_rendering
        if software_rendering == 'software-opengl':
            os.environ['QT_XCB_FORCE_SOFTWARE_OPENGL'] = '1'
        elif software_rendering == 'qt-quick':
            os.environ['QT_QUICK_BACKEND'] = 'software'
        elif software_rendering == 'chromium':
            os.environ['QT_WEBENGINE_DISABLE_NOUVEAU_WORKAROUND'] = '1'
        _warn_qtwe_flags_envvar()
    else:
        assert objects.backend == usertypes.Backend.QtWebKit, objects.backend

    if config.val.qt.force_platform is not None:
        os.environ['QT_QPA_PLATFORM'] = config.val.qt.force_platform
    if config.val.qt.force_platformtheme is not None:
        os.environ['QT_QPA_PLATFORMTHEME'] = config.val.qt.force_platformtheme

    if config.val.window.hide_decoration:
        os.environ['QT_WAYLAND_DISABLE_WINDOWDECORATION'] = '1'

    if config.val.qt.highdpi:
        os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'

    for var, val in config.val.qt.environ.items():
        if val is None and var in os.environ:
            del os.environ[var]
        elif val is not None:
            os.environ[var] = val
