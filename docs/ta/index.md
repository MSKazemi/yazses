---
title: "YazSes — தமிழ்"
description: "YazSes என்பது Linux, macOS மற்றும் Windows ஆகியவற்றில் இணைய இணைப்பு இல்லாமலேயே இயங்கும் குரலை எழுத்தாக மாற்றும் கருவி. `faster-whisper` மூலம் உங்கள் சாதனத்திலேயே பேச்சை மாற்றி, நீங்கள் பயன்படுத்தும் செயலியில் நேரடியாக எழுத்து வடிவமாக மாற்றுகிறது. கிளவுட், API key அல்லது சந்தா எதுவும் தேவையில்லை.
"
alternates:
  en: index.md
---

**Read this in other languages:** [English](../index.md) · [Deutsch](../de/index.md) · [Nederlands](../nl/index.md) · [Tiếng Việt](../vi/index.md) · [Türkçe](../tr/index.md) · [bahasa Indonesia](../id/index.md) · [español](../es/index.md) · [français](../fr/index.md) · [italiano](../it/index.md) · [polski](../pl/index.md) · [português do Brasil](../pt-BR/index.md) · [svenska](../sv/index.md) · [čeština](../cs/index.md) · [ελληνικά](../el/index.md) · [Русский](../ru/index.md) · [українська](../uk/index.md) · [עברית](../he/index.md) · [اردو](../ur/index.md) · [العربية](../ar/index.md) · [فارسی](../fa/index.md) · [हिंदी](../hi/index.md) · [বাংলা](../bn/index.md) · தமிழ் · [తెలుగు](../te/index.md) · [ไทย](../th/index.md) · [日本語](../ja/index.md) · [简体中文](../zh-CN/index.md) · [繁體中文](../zh-TW/index.md) · [한국어](../ko/index.md)
<!-- yazses-l10n: locale=ta; source=README.md; source_sha=3baacb8; scope=partial; status=active; reviewer=@Guruharishb -->



# YazSes

YazSes என்பது Linux, macOS மற்றும் Windows ஆகியவற்றில் இயங்கும் குரலை எழுத்து வடிவமாக மாற்றும் கருவி. இணைய இணைப்பு தேவையில்லை; இது உங்கள் கணினியிலேயே செயல்படும். ஒரு விசையை அழுத்திப் பிடித்து பேசுங்கள். பிறகு விசையை விடும்போது, `faster-whisper` உங்கள் சாதனத்திலேயே பேச்சை எழுத்து வடிவமாக மாற்றி, நீங்கள் பயன்படுத்தும் செயலியில் நேரடியாகத் தட்டச்சு செய்யும். கிளவுட் இல்லை. API key தேவையில்லை. சந்தாவும் இல்லை. எந்தத் தரவும் உங்கள் கணினியை விட்டு வெளியே செல்லாது.


## ஏன் YazSes?

* **இணைய இணைப்பு இல்லாமலேயே இயங்கும்; உங்கள் தனியுரிமையும் பாதுகாக்கப்படும்**

  உங்கள் சாதனத்தின் `CPU`-வில் இயங்கும் `faster-whisper` (`int8`) மூலம் பேச்சு எழுத்தாக மாற்றப்படுகிறது. `GPU`, இணைய இணைப்பு அல்லது கணக்கு எதுவும் தேவையில்லை. ஒலிப்பதிவோ, எழுத்து உள்ளடக்கமோ உங்கள் கணினியை விட்டு வெளியே செல்லாது.

* **எந்தச் செயலியிலும் நேரடியாகத் தட்டச்சு செய்யலாம்**

  ஒரு விசையை அழுத்திப் பிடித்து பேசுங்கள்; பேசி முடித்ததும் விசையை விடுங்கள். நீங்கள் பயன்படுத்தும் செயலி editor ஆக இருந்தாலும், browser, terminal அல்லது chat ஆக இருந்தாலும், எழுத்து நேரடியாக அதில் தோன்றும். `X11` மற்றும் `Wayland` இரண்டிலும் இது இயங்கும்.

* **SSH மற்றும் Remote-SSH வழியாகவும் பயன்படுத்தலாம்**

  YazSes ஒரு குறிப்பிட்ட செயலிக்குள் மட்டும் இயங்குவதில்லை; `OS` மட்டத்தில் எழுத்தை உள்ளிடுகிறது. அதனால் `VS Code` / `Cursor Remote-SSH` panes, integrated terminals, `tmux` மற்றும் container shells போன்றவற்றிலும் இதைப் பயன்படுத்தலாம். பொதுவாக ஒரு செயலிக்குள் மட்டுமே இயங்கும் dictation கருவிகளால் இவற்றை அணுக முடியாது.

* **குரல் கட்டளைகள் மற்றும் macros**

  `regex` இலக்கணம் மூலம் *“undo that”*, *“save file”*, *“go to line 42”* போன்ற குரல் கட்டளைகளை உண்மையான key sequences ஆக மாற்றி செயல்படுத்தலாம்.

* **ஒலிப்பதிவுகளை எழுத்தாக மாற்றலாம்**

  `yazses transcribe meeting.m4a` கட்டளையைப் பயன்படுத்தி எந்த audio/video கோப்பையும் இணைய இணைப்பு இல்லாமலேயே எழுத்தாக மாற்றலாம். `--diarize` மூலம் யார் பேசுகிறார்கள் என்பதையும் தனித்தனியாகக் குறிப்பிடலாம்; subtitles-ஐயும் export செய்யலாம்.

* **அனைவரும் எளிதாகப் பயன்படுத்தும் வகையில் வடிவமைக்கப்பட்டுள்ளது**

  `VAD` calibration, mic-level tuning, dysfluency-friendly mode மற்றும் `EMG` muscle-sensor trigger போன்ற அம்சங்கள் இதில் உள்ளன. இதனால் கைகளைப் பயன்படுத்தாமலேயே YazSes-ஐ இயக்க முடியும்.

* **உங்கள் தேவைக்கேற்ப தானாக மேம்படுத்திக்கொள்ளும்**

  விருப்பத்துடன் இயக்கக்கூடிய, குறியாக்கம் செய்யப்பட்டு சாதனத்திலேயே சேமிக்கப்படும் learning corpus மூலம், உங்கள் சொந்தத் திருத்தங்களைப் பயன்படுத்தி `yazses tune` துல்லியத்தை மேம்படுத்துவதற்கான பரிந்துரைகளை வழங்கும்.

## நிறுவல்

| **தளம்**                              | **நிறுவல் கட்டளை**                                                                         |
| ------------------------------------- | ------------------------------------------------------------------------------------------ |
| **எந்த இயங்குதளமும்** (Python ≥ 3.11) | `pipx install yazses`                                                                      |
| **Linux** (Debian/Ubuntu)             | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)` |

!!! warning "Snap அல்ல"
கட்டுப்படுத்தப்பட்ட Snap-ல் `X11`-ல் மட்டுமே dictation செயல்படும். `Wayland`-ல் பயன்படுத்த, மேலே உள்ள APT script அல்லது `pipx` முறையைப் பயன்படுத்துங்கள். விசை உள்ளீட்டைச் செலுத்தத் தேவையான host `ydotoold` service-ஐ Snap-ஆல் configure செய்யவோ பயன்படுத்தவோ முடியாது.

`X11`-ல் நிறுவிய பிறகு, தேவையான இரண்டு interfaces-ஐ இணைக்கவும்:

```sh
sudo snap install yazses
sudo snap connect yazses:audio-record
sudo snap connect yazses:raw-input
yazses doctor
```

Snap பதிப்புக்கு `yazses setup` தேவையில்லை. அதன் confinement காரணமாக host packages-ஐ நிறுவவோ, groups-ஐ மாற்றவோ, host services-ஐ configure செய்யவோ முடியாது. அதற்குப் பதிலாக, தேவைப்படும் permissions பற்றிய manual checklist-ஐ மட்டுமே அது காட்டும். X11-க்குத் தேவையான dependencies Snap-இலேயே சேர்க்கப்பட்டுள்ளன.

**Snap அல்லாத Linux நிறுவல்களில், ஒரே கட்டளையில் system setup செய்யலாம்:**

```sh
yazses setup        # audio + injection dependencies-ஐ நிறுவி, input group-ல் சேர்த்து, ydotoold-ஐ அமைக்கிறது
# அதன் பிறகு logout செய்து மீண்டும் login செய்யவும் (input-group மாற்றத்திற்கு புதிய login தேவை)
```

இந்தக் கட்டளை `libportaudio2` (audio), X11/Wayland injection tools ஆகியவற்றை நிறுவி, உங்களை `input` group-ல் சேர்க்கும். மேலும், **GNOME/KDE Wayland**-ல் `wtype` தடுக்கப்படுவதால், விசை உள்ளீட்டைச் செலுத்தும் ஒரே வழியான `ydotoold`-ஐ அமைக்கும். இதை எப்போது வேண்டுமானாலும் மீண்டும் இயக்கலாம்; தேவையான மாற்றங்களை மட்டுமே அது செய்யும்.

அதன் பிறகு:

```sh
yazses doctor     # mic, injection backend, permissions ஆகியவற்றைச் சரிபார்க்கவும்
yazses enroll     # microphone-ஐ calibrate செய்யவும் (~30 s)
yazses start      # dictation daemon-ஐ தொடங்கவும்
```

Linux-ல் **Right Alt**, macOS-ல் **Right Option**, Windows-ல் **Right Ctrl** விசையை அழுத்திப் பிடித்து பேசுங்கள். பேசி முடித்ததும் விசையை விடுங்கள். சுமார் ஒரு வினாடிக்குள், focus-ல் உள்ள செயலியில் எழுத்து தோன்றும்.

முதல் முறை இயக்கும்போது ஒரு பேச்சு மாதிரி (சுமார் 148 MB) ஒருமுறை பதிவிறக்கம் செய்யப்படும். அதன்பிறகு இணையமே தேவையில்லை.

## மக்கள் இதை எதற்காகப் பயன்படுத்துகிறார்கள்

* :material-linux: [**Linux-ல் குரல் மூலம் தட்டச்சு**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/voice-dictation-linux.md) — X11, Wayland இரண்டிலும் இயங்கும் dictation
* :material-wave: [**Wayland-ல் குரல் மூலம் dictation**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/voice-dictation-wayland.md) — GNOME, KDE Plasma, sway, Hyprland மற்றும் terminals உட்பட
* :material-shield-lock: [**ரகசியமான, இணைய இணைப்பு இல்லாத வேலைகள்**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/private-offline-dictation.md) — மருத்துவம், சட்டம், air-gapped சூழல்கள்
* :material-code-braces: [**குரல் மூலம் coding**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/voice-coding.md) — spoken symbols, identifiers, LaTeX, git
* :material-microphone-message: [**குரல் மூலம் கட்டுப்படுத்துதல்**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/voice-commands.md) — commands, macros, hands-free actions
* :material-human-cane: [**அணுகல்தன்மை மற்றும் RSI**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/accessibility-rsi-hands-free.md) — hands-free பயன்பாடு, dysfluency-friendly செயல்பாடு
* :material-file-music: [**ஒலிப்பதிவுகளை எழுத்தாக மாற்றுதல்**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/transcribe-audio-offline.md) — இணைய இணைப்பு இல்லாமல், speaker labels உடன்
* :material-code-braces: [**code-ஐ குரல் மூலம் dictation செய்வது**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/dictating-code.md) — identifiers, jargon, punctuation உட்பட
* :material-speedometer: [**model-ஐத் தேர்வு செய்தல்**](https://github.com/MSKazemi/yazses/blob/main/docs/models.md) — அளவிடப்பட்ட accuracy மற்றும் latency அடிப்படையில்
* :material-monitor-multiple: [**platform support**](https://github.com/MSKazemi/yazses/blob/main/docs/platform-support.md) — உங்கள் OS மற்றும் CPU-ல் இது இயங்குமா?
* :material-table-check: [**capability matrix**](https://github.com/MSKazemi/yazses/blob/main/docs/capability-matrix.md) — எந்த இடத்தில் எந்த features வேலை செய்கின்றன, ஏன் வேலை செய்யவில்லை
* :material-tune: [**settings window**](https://github.com/MSKazemi/yazses/blob/main/docs/settings-gui.md) — config file இல்லாமல், ஒவ்வொரு capability-யையும் checkbox மூலம் அமைக்கலாம்
* :material-translate: [**ஒன்றுக்கும் மேற்பட்ட மொழிகள்**](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/multilingual-dictation.md) — English அல்லாத மொழிகள் மற்றும் code-switching

[அனைத்து use cases-ஐப் பார்க்கவும் :octicons-arrow-right-24:](https://github.com/MSKazemi/yazses/blob/main/docs/use-cases/index.md){ .md-button }

## எப்போது இதைப் பயன்படுத்தக் கூடாது

YazSes ஒரு **LLM agent அல்ல**. இது உங்கள் பேச்சை எழுத்தாக மாற்றி, editor மற்றும் terminal commands-ஐ இயக்கும். ஆனால் இணையத்தில் தேடவோ, உங்கள் files-ஐ ஆராய்ந்து reasoning செய்யவோ, உரையாடலைத் தொடர்ந்து நடத்தவோ முடியாது. இது CPU-ல் `faster-whisper`-ஐப் பயன்படுத்துகிறது. சத்தம் அதிகமான microphone-ல் raw accuracy-ஐ மட்டும் ஒப்பிட்டுப் பார்த்தால், cloud service இன்னும் சிறப்பாக இருக்கலாம். மேலும், இது இயல்பாக English-க்கு tune செய்யப்பட்ட `*.en` models-ஐப் பயன்படுத்துகிறது; desktop-ல் மட்டுமே இயங்கும்.

## இது எப்படி வேலை செய்கிறது

```text
Hold hotkey → record audio → VAD gate → faster-whisper (CPU)
            → clean + disfluency filter → command இலக்கணம் (Tier 1 regex)
            → dictate? type it · command? send keys
```

YazSes என்ன செய்கிறது என்பதை உடனடியாகப் புரிந்துகொள்ள இரண்டு indicators உள்ளன. மேல்பட்டியில் இருக்கும் **"Y" tray icon**-ன் நிறம், அதன் தற்போதைய நிலையை நேரடியாகக் காட்டும் (🔵 idle · 🟢 dictating · 🟡 text target இல்லை → clipboard · 🟣 command mode · 🔴 problem). விரும்பினால் sonar overlay-ஐயும் இயக்கலாம்; YazSes listening செய்யும் போது அது உங்கள் cursor அருகில் pulse ஆகும். ஒவ்வொரு நிறத்தின் அர்த்தத்தையும் [Tray icon & overlay](https://github.com/MSKazemi/yazses/blob/main/docs/tray-and-overlay.md) பகுதியில் பார்க்கலாம்.

YazSes CLI-யைப் பற்றிய விளக்கத்தை மட்டும் படிக்காமல், அது எப்படி இயங்குகிறது என்பதை நேரடியாகப் பார்க்க விரும்புகிறீர்களா? [**இங்கேயே அதை இயக்கிப் பாருங்கள்**](https://github.com/MSKazemi/yazses/blob/main/docs/watch-the-cli.md) — `-h` → `about` → `quickstart` → `features` → `status` ஆகியவற்றைக் காட்டும் உண்மையான [asciinema](https://asciinema.org/) recording. அதில் உள்ள text-ஐத் தேர்ந்தெடுத்து copy-paste செய்யலாம். அல்லது உங்கள் terminal-ல்:

```sh
asciinema play docs/demo/yazses-cli.cast
```

## ஆவணங்கள்

* :material-book-open-variant: [**Linux-ல் நிறுவுதல்**](https://github.com/MSKazemi/yazses/blob/main/docs/install-linux.md) · [macOS](https://github.com/MSKazemi/yazses/blob/main/docs/macos-install.md) · [Windows](https://github.com/MSKazemi/yazses/blob/main/docs/windows-install.md)
* :material-console-line: [**CLI reference**](https://github.com/MSKazemi/yazses/blob/main/docs/cli-reference.md) — அனைத்து commands மற்றும் flags
* :material-cog: [**Configuration**](https://github.com/MSKazemi/yazses/blob/main/docs/configuration.md) — `config.toml`-ன் அனைத்து sections
* :material-star-four-points: [**Features**](https://github.com/MSKazemi/yazses/blob/main/docs/features.md) மற்றும் [**v2 preview**](https://github.com/MSKazemi/yazses/blob/main/docs/v2-features.md)
* :material-scale-balance: [**Comparison & alternatives**](https://github.com/MSKazemi/yazses/blob/main/docs/comparison.md) — Talon, Dragon, Wispr Flow ஆகியவற்றுடனான ஒப்பீடு
* :material-frequently-asked-questions: [**FAQ**](https://github.com/MSKazemi/yazses/blob/main/docs/faq.md) — பொதுவான கேள்விகளுக்கான பதில்கள்
* :material-sitemap: [**Architecture**](https://github.com/MSKazemi/yazses/blob/main/docs/architecture.md) மற்றும் [**diagrams**](https://github.com/MSKazemi/yazses/blob/main/docs/diagrams/index.md)
* :material-lifebuoy: [**Troubleshooting**](https://github.com/MSKazemi/yazses/blob/main/docs/troubleshooting.md) மற்றும் [**roadmap**](https://github.com/MSKazemi/yazses/blob/main/docs/roadmap.md)
* :material-flask-outline: [**Research**](https://github.com/MSKazemi/yazses/blob/main/docs/research/index.md) — eye, voice மற்றும் muscle input குறித்த மேற்கோள்களுடன் கூடிய அறிவியல் ஆய்வுகள்
* :material-school-outline: [**Student & research projects**](https://github.com/MSKazemi/yazses/blob/main/docs/research/get-involved.md) — thesis அளவிலான problems மற்றும் open issues

!!! tip "இது ஏன் இப்படி வேலை செய்கிறது என்று ஆர்வமா?"

```text
[research section](research/index.md) என்பது keyboard-க்குப் பிறகான
input குறித்த public, fully-cited notebook. Webcam eye tracking உண்மையில்
எவ்வளவு துல்லியமானது, offline speech recognition எவ்வாறு cloud-ஐ முந்தியது,
மேலும் $50 muscle sensor எப்படி $1,000 EEG headset-ஐவிடச் சிறப்பாகச்
செயல்படுகிறது என்பதையும் இதில் பார்க்கலாம். YazSes-ன் ஒவ்வொரு design
decision-உம் அங்குள்ள measurements-ஐ அடிப்படையாகக் கொண்டது. மேலும்,
open questions-க்கு யார் வேண்டுமானாலும் பங்களிக்கலாம்.
```

## FAQ

**இணைய இணைப்பு இல்லாமலும் இது இயங்குமா?** ஆம் — transcription சாதனத்திலேயே நடைபெறும்; இயல்பாக எந்தத் தகவலும் வெளியே அனுப்பப்படாது.

**எனக்கு எந்த GPU தேவை?** எதுவும் தேவையில்லை. இது CPU-லேயே இயங்கும். குறைந்தபட்சம் 4 GB RAM தேவை; 8 GB இருந்தால் இன்னும் வசதியாக இருக்கும்.

**Wayland-ல் இது இயங்குமா?** ஆம். APT அல்லது `pipx` installation மூலம் பயன்படுத்தலாம் (`wtype`/`ydotool` பயன்படுத்துகிறது). இவற்றில் ஒன்றைப் பயன்படுத்துங்கள்; Snap-ஐத் தவிர்க்கவும். Snap-ன் strict confinement காரணமாக, host injection service-ஐ அதனால் பயன்படுத்த முடியாது. எனவே Wayland applications-ல் result-ஐ type செய்ய முடியாது.

**Talon-க்கு இது மாற்றா?** YazSes இணைய இணைப்பு இல்லாத dictation மற்றும் நடைமுறைக்கு ஏற்ற command இலக்கணம் ஆகியவற்றில் கவனம் செலுத்துகிறது. Talon-ல் மிகவும் advanced scripting capabilities உள்ளன. இரண்டையும் ஒன்றாகப் பயன்படுத்தலாம்.

மேலும் பதில்களுக்கு [**full FAQ**](https://github.com/MSKazemi/yazses/blob/main/docs/faq.md)-ஐப் பார்க்கவும். [**Comparison & alternatives**](https://github.com/MSKazemi/yazses/blob/main/docs/comparison.md) பகுதியில் side-by-side comparison உள்ளது.

---

Apache-2.0 license-ன் கீழ் வெளியிடப்பட்டுள்ளது. YazSes உங்களுக்குப் பயனுள்ளதாக இருந்தால், [GitHub](https://github.com/MSKazemi/yazses)-ல் ⭐ கொடுங்கள். இதனால் மற்றவர்களும் இதைக் கண்டுபிடிக்க உதவும்.

**பங்களிக்க விரும்புகிறீர்களா?** [Contributing](https://github.com/MSKazemi/yazses/blob/main/docs/contributing.md) பகுதியைப் பார்க்கவும் — README-ஐ மொழிபெயர்ப்பது, நீங்கள் ஏற்கனவே பயன்படுத்தும் config-ஐப் பகிர்வது, உங்களுக்கு நன்றாக வேலை செய்த microphone-ஐச் சேர்ப்பது போன்ற code தேவையில்லாத பல பணிகளும் உள்ளன.

## தனியுரிமை

ஒலி உங்கள் கணினியிலேயே எழுத்தாக மாற்றப்படுகிறது; அது எங்கும் அனுப்பப்படுவதில்லை. தொலைஅளவீடு இல்லை; மேகக்கணிக்கான பாதையும் இல்லை.

## மேலும்

மீதமுள்ள ஆவணங்கள் தற்போது ஆங்கிலத்தில் மட்டுமே உள்ளன.

* [ஆவணங்கள்](https://mskazemi.com/yazses/)
* [முழு ஆங்கில README](https://github.com/MSKazemi/yazses#readme)
* [சிக்கல்களும் கேள்விகளும்](https://github.com/MSKazemi/yazses/issues)

---


## Contributors

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi"><img src="https://avatars.githubusercontent.com/u/13011878?v=4?s=100" width="100px;" alt="Mohsen Seyedkazemi Ardebili"/><br /><sub><b>Mohsen Seyedkazemi Ardebili</b></sub></a><br /><a href="#maintenance-MSKazemi" title="Maintenance">🚧</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/lntutor"><img src="https://avatars.githubusercontent.com/u/1948922?v=4?s=100" width="100px;" alt="lntutor"/><br /><sub><b>lntutor</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=lntutor" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/HeaTTap"><img src="https://avatars.githubusercontent.com/u/83951176?v=4?s=100" width="100px;" alt="HeaTTap"/><br /><sub><b>HeaTTap</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=HeaTTap" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jackie-cqz"><img src="https://avatars.githubusercontent.com/u/88996311?v=4?s=100" width="100px;" alt="jackie-cqz"/><br /><sub><b>jackie-cqz</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=jackie-cqz" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Parinitha-26"><img src="https://avatars.githubusercontent.com/u/199358281?v=4?s=100" width="100px;" alt="Parinitha-26"/><br /><sub><b>Parinitha-26</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Parinitha-26" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AshSgDe29071999"><img src="https://avatars.githubusercontent.com/u/192003854?v=4?s=100" width="100px;" alt="AshSgDe29071999"/><br /><sub><b>AshSgDe29071999</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Maqbool61"><img src="https://avatars.githubusercontent.com/u/68494045?v=4?s=100" width="100px;" alt="Maqbool Ahmed"/><br /><sub><b>Maqbool Ahmed</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Maqbool61" title="Code">💻</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn"><img src="https://avatars.githubusercontent.com/u/145488564?v=4?s=100" width="100px;" alt="Renji"/><br /><sub><b>Renji</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Tests">⚠️</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Documentation">📖</a> <a href="#security-waterlemonnn" title="Security">🛡️</a> <a href="#infra-waterlemonnn" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/slegarraga"><img src="https://avatars.githubusercontent.com/u/64795732?v=4?s=100" width="100px;" alt="Sebastian Legarraga"/><br /><sub><b>Sebastian Legarraga</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=slegarraga" title="Code">💻</a> <a href="#userTesting-slegarraga" title="User Testing">📓</a> <a href="#platform-slegarraga" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/YossiMH"><img src="https://avatars.githubusercontent.com/u/21257793?v=4?s=100" width="100px;" alt="YossiMH"/><br /><sub><b>YossiMH</b></sub></a><br /><a href="#ideas-YossiMH" title="Ideas, Planning, & Feedback">🤔</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3AYossiMH" title="Bug reports">🐛</a> <a href="#research-YossiMH" title="Research">🔬</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Prithvi4904"><img src="https://avatars.githubusercontent.com/u/216231806?v=4?s=100" width="100px;" alt="Prithvi4904"/><br /><sub><b>Prithvi4904</b></sub></a><br /><a href="#translation-Prithvi4904" title="Translation">🌍</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/4nmus"><img src="https://avatars.githubusercontent.com/u/145120721?v=4?s=100" width="100px;" alt="4nmus"/><br /><sub><b>4nmus</b></sub></a><br /><a href="#translation-4nmus" title="Translation">🌍</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Mr-Neutr0n"><img src="https://avatars.githubusercontent.com/u/64578610?v=4?s=100" width="100px;" alt="hari"/><br /><sub><b>hari</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Mr-Neutr0n" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mercael91"><img src="https://avatars.githubusercontent.com/u/257655913?v=4?s=100" width="100px;" alt="mercael"/><br /><sub><b>mercael</b></sub></a><br /><a href="#infra-mercael91" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a> <a href="https://github.com/MSKazemi/yazses/commits?author=mercael91" title="Documentation">📖</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/happytester-funbugs"><img src="https://avatars.githubusercontent.com/u/184687761?v=4?s=100" width="100px;" alt="Tanya Martin-McClellan"/><br /><sub><b>Tanya Martin-McClellan</b></sub></a><br /><a href="#userTesting-happytester-funbugs" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Ahappytester-funbugs" title="Bug reports">🐛</a> <a href="#platform-happytester-funbugs" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AtmanActive"><img src="https://avatars.githubusercontent.com/u/7526717?v=4?s=100" width="100px;" alt="AtmanActive"/><br /><sub><b>AtmanActive</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/issues?q=author%3AAtmanActive" title="Bug reports">🐛</a> <a href="#userTesting-AtmanActive" title="User Testing">📓</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/hoti-code"><img src="https://avatars.githubusercontent.com/u/320443384?v=4?s=100" width="100px;" alt="hoti-code"/><br /><sub><b>hoti-code</b></sub></a><br /><a href="#userTesting-hoti-code" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Ahoti-code" title="Bug reports">🐛</a> <a href="#platform-hoti-code" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jayavandhiniMK"><img src="https://avatars.githubusercontent.com/u/221181058?v=4?s=100" width="100px;" alt="Jayavandhini M K"/><br /><sub><b>Jayavandhini M K</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=jayavandhiniMK" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/visheshbpatel"><img src="https://avatars.githubusercontent.com/u/206997413?v=4?s=100" width="100px;" alt="Vishesh Patel"/><br /><sub><b>Vishesh Patel</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=visheshbpatel" title="Documentation">📖</a> <a href="#userTesting-visheshbpatel" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Avisheshbpatel" title="Bug reports">🐛</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/fall-water-zxc"><img src="https://avatars.githubusercontent.com/u/210990993?v=4?s=100" width="100px;" alt="fall-water-zxc"/><br /><sub><b>fall-water-zxc</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=fall-water-zxc" title="Documentation">📖</a> <a href="#userTesting-fall-water-zxc" title="User Testing">📓</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3Afall-water-zxc" title="Bug reports">🐛</a> <a href="#platform-fall-water-zxc" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/greatlord"><img src="https://avatars.githubusercontent.com/u/2506501?v=4?s=100" width="100px;" alt="Magnus Olsen"/><br /><sub><b>Magnus Olsen</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/issues?q=author%3Agreatlord" title="Bug reports">🐛</a> <a href="#ideas-greatlord" title="Ideas, Planning, & Feedback">🤔</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Akgithub2028"><img src="https://avatars.githubusercontent.com/u/181275449?v=4?s=100" width="100px;" alt="Aayaann Kausar"/><br /><sub><b>Aayaann Kausar</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Akgithub2028" title="Documentation">📖</a> <a href="#userTesting-Akgithub2028" title="User Testing">📓</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/auroraxo"><img src="https://avatars.githubusercontent.com/u/325296939?v=4?s=100" width="100px;" alt="Aurora"/><br /><sub><b>Aurora</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=auroraxo" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=auroraxo" title="Tests">⚠️</a> <a href="#platform-auroraxo" title="Packaging/porting to new platform">📦</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/YuuGR1337"><img src="https://avatars.githubusercontent.com/u/241930202?v=4?s=100" width="100px;" alt="Elkero"/><br /><sub><b>Elkero</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=YuuGR1337" title="Documentation">📖</a> <a href="#translation-YuuGR1337" title="Translation">🌍</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3AYuuGR1337" title="Bug reports">🐛</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->
