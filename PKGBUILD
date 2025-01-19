# Maintainer: Florian Bruhin (The Compiler) <archlinux.org@the-compiler.org>
# Contributor: Morten Linderud <foxboron@archlinux.org>
# Contributor: Pierre Neidhardt <ambrevar@gmail.com>
# vim: set ts=4 sw=4 et ft=sh:

pkgname=qutebrowser-galicarnax
pkgver=3.4.0.r149.g4d9d839c6
pkgrel=1
pkgdesc="A keyboard-driven, vim-like browser based on PyQt6"
arch=("any")
url="https://www.qutebrowser.org/"
license=("GPL")
depends=("python-jinja" "python-pyqt6" "python-yaml" "python-pyqt6-webengine")
makedepends=("asciidoc" "python-setuptools")
optdepends=("python-adblock: ABP-style adblocking"
            "pdfjs: displaying PDF in-browser"
            "python-pygments"
            "python-i3ipc: hack for activating window in Sway")
options=(!emptydirs)
conflicts=('qutebrowser')
provides=('qutebrowser')
source=()
sha256sums=('SKIP')

pkgver() {
    # cd "$srcdir/qutebrowser"
    cd "$startdir"
    # Minor releases are not part of the master branch
    _tag=$(git tag --sort=v:refname | tail -n1)
    printf '%s.r%s.g%s' "${_tag#v}" "$(git rev-list "$_tag"..HEAD --count)" "$(git rev-parse --short HEAD)"
}

build() {
    # cd "$srcdir/qutebrowser"
    cd "$startdir"
    python scripts/asciidoc2html.py
    a2x -f manpage doc/qutebrowser.1.asciidoc
    python setup.py build
}

package() {
    # cd "$srcdir/qutebrowser"
    cd "$startdir"
    make -f misc/Makefile DESTDIR="$pkgdir" PREFIX=/usr install
}
