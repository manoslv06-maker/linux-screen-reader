# linux-screen-reader

[English](README.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md) · [Русский](README.ru.md) · **हिन्दी**

Linux के लिए एक स्क्रीन रीडर, जो NVDA जैसा ही इस्तेमाल होता है: NVDA कुंजी (Insert या Caps Lock), डेस्कटॉप और लैपटॉप लेआउट, वेब पर ब्राउज़ मोड और फ़ोकस मोड, इनपुट सहायता, `gestures.ini` और ऐड-ऑन। यह Python 3 में लिखा गया है और AT-SPI2, evdev/uinput, Speech Dispatcher और BrlAPI पर चलता है।

पैकेज और कमांड का नाम `nvda-linux` है। यह प्रोजेक्ट **NV Access या आधिकारिक NVDA से जुड़ा नहीं है**; यह सिर्फ़ उन लोगों के लिए वही इस्तेमाल का तरीका देता है जो Windows पर NVDA जानते हैं।

> ⚠️ **प्रायोगिक संस्करण (0.1.0.dev0)।** अभी रोज़ाना इस्तेमाल के लिए तैयार नहीं है। यह एक वर्चुअल मशीन में Fedora 45 और GNOME 51 पर चला, लेकिन किसी दृष्टिबाधित व्यक्ति ने इसे अभी तक रोज़ाना इस्तेमाल नहीं किया है, और साउंड वाली मशीन पर आवाज़ अभी सुनकर जाँची नहीं गई है।

## क्या पहले से काम करता है

असली सिस्टम पर जाँचा गया (Fedora 45, GNOME 51, Firefox):

- Speech Dispatcher से बोलना, टाइप किए अक्षरों की गूँज (पासवर्ड फ़ील्ड में "तारांकन");
- evdev/uinput से कीबोर्ड पकड़ना, NVDA कुंजी, NVDA+T (शीर्षक), फ़ोकस की घोषणा;
- Firefox में ब्राउज़ मोड: पेज लोड होने पर पढ़ना, H/B (अगला शीर्षक/बटन), तीर कुंजियों से पंक्ति-दर-पंक्ति।

स्वचालित परीक्षणों (279) से जाँचा गया, पर असली मशीन पर अभी पुष्टि नहीं हुई: "सब पढ़ें" जिसमें कर्सर आवाज़ के साथ चलता है, पूरा त्वरित नेविगेशन (K, F, T, D, 1–6...), तालिकाएँ, तत्वों की सूची, ब्रेल, GTK 4 इंटरफ़ेस, ऐड-ऑन।

## इंस्टॉल करें

PyGObject 3.50 या नया चाहिए: **Debian 13, Ubuntu 25.04 या नया, Fedora 41+, openSUSE Tumbleweed या Arch**। Ubuntu 24.04 पर अभी काम नहीं करता।

सबसे आसान तरीका [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases) पेज का एकल इंस्टॉलर है। यह डिस्ट्रीब्यूशन पहचानकर apt, dnf, zypper या pacman इस्तेमाल करता है:

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # इंस्टॉल करता है (input समूह बदलने से पहले पूछता है)
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

सोर्स कोड से इंस्टॉलर बनाने के लिए [पैकेज बनाना](#पैकेज-बनाना) देखें।

### पहली बार आज़माने से पहले

स्क्रीन रीडर पूरा कीबोर्ड अपने कब्ज़े में लेता है। **लॉगिन का एक वैकल्पिक रास्ता** (SSH या कोई दूसरा टेक्स्ट कंसोल) तैयार रखें और याद रखें: **Ctrl+Alt+Shift+Esc** रीडर को बंद करता है और कीबोर्ड वापस देता है।

```sh
sudo usermod -aG input $USER      # फिर लॉग आउट करके दोबारा लॉग इन करें
nvda-linux --check-permissions    # जाँच
nvda-linux --debug                # टर्मिनल में विस्तृत लॉग के साथ चलाएँ
systemctl --user enable --now nvda-linux.service   # सत्र के साथ शुरू करें (वैकल्पिक)
```

लॉग `~/.local/state/nvda-linux/nvda.log` में है।

## विकास

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

परीक्षण नकली ऑब्जेक्ट इस्तेमाल करते हैं (इन्हें AT-SPI2, ऑडियो या कीबोर्ड की ज़रूरत नहीं)। इन्हें Linux पर चलाएँ: Windows पर इनमें से कुछ नहीं चलते।

दस्तावेज़ (पुर्तगाली में):

- [docs/ROADMAP.md](docs/ROADMAP.md): योजनाबद्ध चरण और संस्करण;
- [docs/platform/README.md](docs/platform/README.md): इवेंट लूप, आवाज़, कीबोर्ड, ब्रेल और पैकेजिंग;
- [docs/semantics/README.md](docs/semantics/README.md): AT-SPI2, इवेंट, ब्राउज़ मोड और इंटरफ़ेस;
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md): ऐड-ऑन;
- [CLAUDE.md](CLAUDE.md): वर्तमान स्थिति और अगले कदम।

### पैकेज बनाना

हर स्क्रिप्ट अपने संबंधित डिस्ट्रीब्यूशन पर चलती है और `dist/` में लिखती है:

| स्क्रिप्ट | क्या बनाती है |
|---|---|
| `packaging/build-packages.sh` | `.deb` और `.tar.gz` सोर्स (Debian/Ubuntu) |
| `packaging/build-rpm.sh` | `.rpm` (मशीन के अनुसार Fedora या openSUSE) |
| `packaging/build-arch.sh` | `.pkg.tar.zst` (Arch, सामान्य उपयोगकर्ता के रूप में) |
| `packaging/build-installer.sh` | ऊपर का सब कुछ शामिल `nvda-linux-instalador-<संस्करण>.run` |

## लाइसेंस

[GPL-2.0-or-later](LICENSE)।
