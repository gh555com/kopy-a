from PyQt5.QtCore import QUrl
from PyQt5.QtMultimedia import QSoundEffect
sound = QSoundEffect()
sound.setSource(QUrl.fromLocalFile("E:/s/wol/py/kope/assets/1.mp3"))
sound.play()
