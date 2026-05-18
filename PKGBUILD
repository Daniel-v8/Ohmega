pkgname=ohmega
pkgver=1.1.1
pkgrel=1
pkgdesc=Ohmega normalizes the loudness of your audio files using the EBU R128 standard.
arch=('any')
url=https://ohmega.dany-rcmodelar.workers.dev/
license=('MIT')

depends=('python' 'python-pyqt6' 'python-mutagen' 'ffmpeg')

source=("git+https://github.com/Daniel-v8/Ohmega.git")
sha256sums=('SKIP')

package() {
	cd "$srcdir/Ohmega"

	install -d "$pkgdir/usr/share/$pkgname"
	cp main.py "$pkgdir/usr/share/$pkgname/"
	install -Dm644 ohmega.png "$pkgdir/usr/share/$pkgname/"

	install -Dm755 scripts/launcher.sh "$pkgdir/usr/bin/ohmega"
}