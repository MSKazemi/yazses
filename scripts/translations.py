"""Per-locale strings for the README translations.

The English reference for every key is in `_EN` below. Everything else is a
translation of it, and this file is the thing a reviewer edits — the generator
never touches prose.

**Nothing here may contain a `yazses …` command.** Commands are copied verbatim
from the English README by the generator, because a translated command is a
command that does not exist, and `scripts/check-translations.py` fails the build
if one appears.

Every locale here is `status=draft`: machine-assisted and not yet reviewed by a
native speaker. That is stated in the file itself, in the reader's language, so
nobody mistakes it for reviewed work — and reviewing one is a much smaller task
than translating 400 lines from scratch, which is the point.
"""

from __future__ import annotations

_EN = {
    "draft_title": "Draft translation",
    "draft_body": "Machine-assisted and not yet reviewed by a native speaker.",
    "pitch": (
        "YazSes is a free, open-source, offline voice dictation daemon for Linux, "
        "macOS and Windows. Hold a key, speak, release — the text appears in "
        "whatever you are typing into. Everything runs on your own machine: no "
        "cloud, no account, no subscription."
    ),
    "install_heading": "Install",
    "platform": "Platform",
    "command": "Command",
    "any_os": "Any OS",
    "first_run": (
        "The first run downloads a speech model once (about 148 MB). After that it "
        "needs no network at all."
    ),
    "does_heading": "What it does",
    "does_1_title": "Dictation",
    "does_1": "Hold the hotkey, speak, release. The text is typed into the focused window.",
    "does_2_title": "Voice commands",
    "does_2": "Say “save file” or “go to line 40” and it acts, instead of typing the words.",
    "does_3_title": "Meetings and recordings",
    "does_3": (
        "Transcribe an audio file, or capture a whole meeting with speaker labels — "
        "all offline."
    ),
    "privacy_heading": "Privacy",
    "privacy": (
        "Audio is transcribed on your machine and is never sent anywhere. There is "
        "no telemetry and no cloud path."
    ),
    "more_heading": "More",
    "more": "The rest of the documentation is in English for now.",
    "link_docs": "Documentation",
    "link_readme": "The full English README",
    "link_issues": "Issues and questions",
}


def _t(**overrides) -> dict:
    """A locale's strings, falling back to English for anything not translated."""
    return {**_EN, **overrides}


LOCALES: dict[str, dict] = {
    "es": {"name": "español", "issue": 170, "strings": _t(
        draft_title="Traducción preliminar",
        draft_body="Asistida por máquina y aún sin revisar por un hablante nativo.",
        pitch=(
            "YazSes es un demonio de dictado por voz libre, de código abierto y sin "
            "conexión, para Linux, macOS y Windows. Mantén pulsada una tecla, habla y "
            "suéltala: el texto aparece donde estés escribiendo. Todo se ejecuta en tu "
            "propia máquina: sin nube, sin cuenta y sin suscripción."),
        install_heading="Instalación", platform="Plataforma", command="Comando",
        any_os="Cualquier sistema",
        first_run=("La primera ejecución descarga una vez un modelo de voz (unos 148 MB). "
                   "Después no necesita red en absoluto."),
        does_heading="Qué hace", does_1_title="Dictado",
        does_1="Mantén la tecla, habla y suelta. El texto se escribe en la ventana activa.",
        does_2_title="Comandos de voz",
        does_2="Di «guardar archivo» o «ir a la línea 40» y actúa, en vez de escribir las palabras.",
        does_3_title="Reuniones y grabaciones",
        does_3=("Transcribe un archivo de audio o graba una reunión entera con etiquetas "
                "de hablante, todo sin conexión."),
        privacy_heading="Privacidad",
        privacy=("El audio se transcribe en tu máquina y nunca se envía a ninguna parte. "
                 "No hay telemetría ni ruta a la nube."),
        more_heading="Más", more="El resto de la documentación está por ahora en inglés.",
        link_docs="Documentación", link_readme="README completo en inglés",
        link_issues="Incidencias y preguntas")},

    "pt-BR": {"name": "português do Brasil", "issue": 174, "strings": _t(
        draft_title="Tradução preliminar",
        draft_body="Assistida por máquina e ainda não revisada por um falante nativo.",
        pitch=(
            "O YazSes é um daemon de ditado por voz livre, de código aberto e offline, "
            "para Linux, macOS e Windows. Segure uma tecla, fale e solte: o texto aparece "
            "onde você estiver digitando. Tudo roda na sua própria máquina: sem nuvem, "
            "sem conta e sem assinatura."),
        install_heading="Instalação", platform="Plataforma", command="Comando",
        any_os="Qualquer sistema",
        first_run=("A primeira execução baixa um modelo de fala uma única vez (cerca de "
                   "148 MB). Depois disso, não precisa de rede alguma."),
        does_heading="O que ele faz", does_1_title="Ditado",
        does_1="Segure a tecla, fale e solte. O texto é digitado na janela em foco.",
        does_2_title="Comandos de voz",
        does_2="Diga “salvar arquivo” ou “ir para a linha 40” e ele age, em vez de digitar as palavras.",
        does_3_title="Reuniões e gravações",
        does_3=("Transcreva um arquivo de áudio ou capture uma reunião inteira com "
                "identificação de quem falou — tudo offline."),
        privacy_heading="Privacidade",
        privacy=("O áudio é transcrito na sua máquina e nunca é enviado a lugar nenhum. "
                 "Não há telemetria nem caminho para a nuvem."),
        more_heading="Mais", more="O restante da documentação está em inglês por enquanto.",
        link_docs="Documentação", link_readme="README completo em inglês",
        link_issues="Problemas e dúvidas")},

    "fr": {"name": "français", "issue": 175, "strings": _t(
        draft_title="Traduction provisoire",
        draft_body="Assistée par machine et pas encore relue par un locuteur natif.",
        pitch=(
            "YazSes est un démon de dictée vocale libre, open source et hors ligne, pour "
            "Linux, macOS et Windows. Maintenez une touche, parlez, relâchez : le texte "
            "apparaît là où vous écrivez. Tout s'exécute sur votre machine : pas de nuage, "
            "pas de compte, pas d'abonnement."),
        install_heading="Installation", platform="Plateforme", command="Commande",
        any_os="Tout système",
        first_run=("Le premier lancement télécharge un modèle vocal une seule fois "
                   "(environ 148 Mo). Ensuite, aucun réseau n'est nécessaire."),
        does_heading="Ce qu'il fait", does_1_title="Dictée",
        does_1="Maintenez la touche, parlez, relâchez. Le texte est saisi dans la fenêtre active.",
        does_2_title="Commandes vocales",
        does_2="Dites « enregistrer le fichier » ou « aller à la ligne 40 » et il agit, au lieu d'écrire les mots.",
        does_3_title="Réunions et enregistrements",
        does_3=("Transcrivez un fichier audio, ou capturez une réunion entière avec "
                "identification des intervenants — entièrement hors ligne."),
        privacy_heading="Confidentialité",
        privacy=("L'audio est transcrit sur votre machine et n'est jamais envoyé ailleurs. "
                 "Aucune télémétrie, aucun passage par le nuage."),
        more_heading="Pour aller plus loin",
        more="Le reste de la documentation est pour l'instant en anglais.",
        link_docs="Documentation", link_readme="Le README complet en anglais",
        link_issues="Problèmes et questions")},

    "de": {"name": "Deutsch", "issue": 176, "strings": _t(
        draft_title="Vorläufige Übersetzung",
        draft_body="Maschinell unterstützt und noch nicht von einem Muttersprachler geprüft.",
        pitch=(
            "YazSes ist ein freier, quelloffener Offline-Dienst für Spracheingabe unter "
            "Linux, macOS und Windows. Taste gedrückt halten, sprechen, loslassen — der "
            "Text erscheint dort, wo Sie gerade schreiben. Alles läuft auf Ihrem eigenen "
            "Rechner: keine Cloud, kein Konto, kein Abo."),
        install_heading="Installation", platform="Plattform", command="Befehl",
        any_os="Beliebiges System",
        first_run=("Beim ersten Start wird einmalig ein Sprachmodell heruntergeladen "
                   "(etwa 148 MB). Danach ist überhaupt kein Netz mehr nötig."),
        does_heading="Was es kann", does_1_title="Diktat",
        does_1="Taste halten, sprechen, loslassen. Der Text wird in das aktive Fenster geschrieben.",
        does_2_title="Sprachbefehle",
        does_2="Sagen Sie „Datei speichern“ oder „gehe zu Zeile 40“ — es handelt, statt die Wörter zu tippen.",
        does_3_title="Besprechungen und Aufnahmen",
        does_3=("Transkribieren Sie eine Audiodatei oder nehmen Sie eine ganze Besprechung "
                "mit Sprecherkennung auf — vollständig offline."),
        privacy_heading="Datenschutz",
        privacy=("Audio wird auf Ihrem Rechner transkribiert und niemals irgendwohin "
                 "gesendet. Es gibt keine Telemetrie und keinen Cloud-Pfad."),
        more_heading="Mehr", more="Die übrige Dokumentation ist derzeit auf Englisch.",
        link_docs="Dokumentation", link_readme="Die vollständige englische README",
        link_issues="Probleme und Fragen")},

    "it": {"name": "italiano", "issue": 197, "strings": _t(
        draft_title="Traduzione preliminare",
        draft_body="Assistita da macchina e non ancora revisionata da un madrelingua.",
        pitch=(
            "YazSes è un daemon di dettatura vocale libero, open source e offline per "
            "Linux, macOS e Windows. Tieni premuto un tasto, parla, rilascia: il testo "
            "compare dove stai scrivendo. Tutto gira sulla tua macchina: niente cloud, "
            "nessun account, nessun abbonamento."),
        install_heading="Installazione", platform="Piattaforma", command="Comando",
        any_os="Qualsiasi sistema",
        first_run=("Il primo avvio scarica una volta sola un modello vocale (circa 148 MB). "
                   "Dopodiché non serve alcuna rete."),
        does_heading="Cosa fa", does_1_title="Dettatura",
        does_1="Tieni premuto il tasto, parla, rilascia. Il testo viene scritto nella finestra attiva.",
        does_2_title="Comandi vocali",
        does_2="Di' «salva il file» o «vai alla riga 40» e agisce, invece di scrivere le parole.",
        does_3_title="Riunioni e registrazioni",
        does_3=("Trascrivi un file audio, o registra un'intera riunione con l'indicazione "
                "di chi ha parlato — tutto offline."),
        privacy_heading="Privacy",
        privacy=("L'audio viene trascritto sulla tua macchina e non è mai inviato da "
                 "nessuna parte. Nessuna telemetria e nessun percorso verso il cloud."),
        more_heading="Altro", more="Il resto della documentazione è per ora in inglese.",
        link_docs="Documentazione", link_readme="Il README completo in inglese",
        link_issues="Segnalazioni e domande")},

    "nl": {"name": "Nederlands", "issue": 194, "strings": _t(
        draft_title="Voorlopige vertaling",
        draft_body="Machinaal ondersteund en nog niet nagekeken door een moedertaalspreker.",
        pitch=(
            "YazSes is een vrije, opensource, offline dienst voor spraakdictaat op Linux, "
            "macOS en Windows. Houd een toets ingedrukt, spreek, laat los — de tekst "
            "verschijnt waar je aan het typen bent. Alles draait op je eigen machine: "
            "geen cloud, geen account, geen abonnement."),
        install_heading="Installatie", platform="Platform", command="Opdracht",
        any_os="Elk systeem",
        first_run=("De eerste keer wordt eenmalig een spraakmodel gedownload (ongeveer "
                   "148 MB). Daarna is er helemaal geen netwerk meer nodig."),
        does_heading="Wat het doet", does_1_title="Dictaat",
        does_1="Houd de toets vast, spreek, laat los. De tekst wordt in het actieve venster getypt.",
        does_2_title="Spraakopdrachten",
        does_2="Zeg “bestand opslaan” of “ga naar regel 40” en het handelt, in plaats van de woorden te typen.",
        does_3_title="Vergaderingen en opnamen",
        does_3=("Transcribeer een audiobestand of neem een hele vergadering op met "
                "sprekerlabels — volledig offline."),
        privacy_heading="Privacy",
        privacy=("Audio wordt op je eigen machine getranscribeerd en nooit ergens "
                 "naartoe gestuurd. Er is geen telemetrie en geen route naar de cloud."),
        more_heading="Meer", more="De rest van de documentatie is voorlopig in het Engels.",
        link_docs="Documentatie", link_readme="De volledige Engelse README",
        link_issues="Problemen en vragen")},

    "pl": {"name": "polski", "issue": 200, "strings": _t(
        draft_title="Tłumaczenie robocze",
        draft_body="Wspomagane maszynowo i jeszcze nieprzejrzane przez native speakera.",
        pitch=(
            "YazSes to wolny, otwartoźródłowy i działający offline demon dyktowania głosem "
            "dla Linuksa, macOS-a i Windowsa. Przytrzymaj klawisz, mów, puść — tekst "
            "pojawia się tam, gdzie właśnie piszesz. Wszystko działa na twoim komputerze: "
            "bez chmury, bez konta, bez abonamentu."),
        install_heading="Instalacja", platform="Platforma", command="Polecenie",
        any_os="Dowolny system",
        first_run=("Pierwsze uruchomienie jednorazowo pobiera model mowy (około 148 MB). "
                   "Potem sieć nie jest już w ogóle potrzebna."),
        does_heading="Co potrafi", does_1_title="Dyktowanie",
        does_1="Przytrzymaj klawisz, mów, puść. Tekst zostaje wpisany w aktywne okno.",
        does_2_title="Polecenia głosowe",
        does_2="Powiedz „zapisz plik” albo „przejdź do linii 40”, a wykona to zamiast wpisywać słowa.",
        does_3_title="Spotkania i nagrania",
        does_3=("Przepisz plik audio albo nagraj całe spotkanie z oznaczeniem mówiących — "
                "w całości offline."),
        privacy_heading="Prywatność",
        privacy=("Dźwięk jest przetwarzany na twoim komputerze i nigdy nigdzie nie jest "
                 "wysyłany. Nie ma telemetrii ani żadnej ścieżki do chmury."),
        more_heading="Więcej", more="Reszta dokumentacji jest na razie po angielsku.",
        link_docs="Dokumentacja", link_readme="Pełny README po angielsku",
        link_issues="Zgłoszenia i pytania")},

    "cs": {"name": "čeština", "issue": 193, "strings": _t(
        draft_title="Pracovní překlad",
        draft_body="Strojově podpořený a zatím nezkontrolovaný rodilým mluvčím.",
        pitch=(
            "YazSes je svobodný, otevřený a offline démon pro hlasovou diktaci na Linuxu, "
            "macOS a Windows. Podržte klávesu, mluvte, pusťte — text se objeví tam, kam "
            "právě píšete. Vše běží na vašem počítači: žádný cloud, žádný účet, žádné "
            "předplatné."),
        install_heading="Instalace", platform="Platforma", command="Příkaz",
        any_os="Libovolný systém",
        first_run=("Při prvním spuštění se jednou stáhne řečový model (asi 148 MB). "
                   "Potom už síť není vůbec potřeba."),
        does_heading="Co umí", does_1_title="Diktování",
        does_1="Podržte klávesu, mluvte, pusťte. Text se napíše do aktivního okna.",
        does_2_title="Hlasové příkazy",
        does_2="Řekněte „ulož soubor“ nebo „jdi na řádek 40“ a provede to, místo aby slova napsal.",
        does_3_title="Schůzky a nahrávky",
        does_3=("Přepište zvukový soubor nebo zaznamenejte celou schůzku s označením "
                "mluvčích — zcela offline."),
        privacy_heading="Soukromí",
        privacy=("Zvuk se přepisuje na vašem počítači a nikam se neodesílá. Není zde "
                 "žádná telemetrie ani cesta do cloudu."),
        more_heading="Další", more="Zbytek dokumentace je zatím v angličtině.",
        link_docs="Dokumentace", link_readme="Úplný anglický README",
        link_issues="Hlášení a dotazy")},

    "sv": {"name": "svenska", "issue": 201, "strings": _t(
        draft_title="Preliminär översättning",
        draft_body="Maskinstödd och ännu inte granskad av någon med språket som modersmål.",
        pitch=(
            "YazSes är en fri, öppen och offline tjänst för röstdiktering på Linux, macOS "
            "och Windows. Håll ned en tangent, tala, släpp — texten dyker upp där du "
            "skriver. Allt körs på din egen dator: inget moln, inget konto, ingen "
            "prenumeration."),
        install_heading="Installation", platform="Plattform", command="Kommando",
        any_os="Valfritt system",
        first_run=("Första körningen hämtar en talmodell en gång (cirka 148 MB). Därefter "
                   "behövs inget nätverk alls."),
        does_heading="Vad den gör", does_1_title="Diktering",
        does_1="Håll ned tangenten, tala, släpp. Texten skrivs in i det aktiva fönstret.",
        does_2_title="Röstkommandon",
        does_2="Säg ”spara filen” eller ”gå till rad 40” så utförs det, i stället för att orden skrivs.",
        does_3_title="Möten och inspelningar",
        does_3=("Transkribera en ljudfil eller spela in ett helt möte med talaretiketter — "
                "helt offline."),
        privacy_heading="Integritet",
        privacy=("Ljudet transkriberas på din dator och skickas aldrig någonstans. Det "
                 "finns ingen telemetri och ingen väg till molnet."),
        more_heading="Mer", more="Resten av dokumentationen är på engelska tills vidare.",
        link_docs="Dokumentation", link_readme="Den fullständiga engelska README-filen",
        link_issues="Ärenden och frågor")},

    "el": {"name": "ελληνικά", "issue": 195, "strings": _t(
        draft_title="Προσωρινή μετάφραση",
        draft_body="Με μηχανική υποβοήθηση και χωρίς έλεγχο από φυσικό ομιλητή.",
        pitch=(
            "Το YazSes είναι ένας ελεύθερος, ανοιχτού κώδικα και εκτός σύνδεσης δαίμονας "
            "φωνητικής υπαγόρευσης για Linux, macOS και Windows. Κρατήστε ένα πλήκτρο, "
            "μιλήστε, αφήστε το — το κείμενο εμφανίζεται εκεί που γράφετε. Όλα εκτελούνται "
            "στον δικό σας υπολογιστή: χωρίς νέφος, χωρίς λογαριασμό, χωρίς συνδρομή."),
        install_heading="Εγκατάσταση", platform="Πλατφόρμα", command="Εντολή",
        any_os="Οποιοδήποτε σύστημα",
        first_run=("Η πρώτη εκτέλεση κατεβάζει μία φορά ένα μοντέλο ομιλίας (περίπου "
                   "148 MB). Μετά δεν χρειάζεται καθόλου δίκτυο."),
        does_heading="Τι κάνει", does_1_title="Υπαγόρευση",
        does_1="Κρατήστε το πλήκτρο, μιλήστε, αφήστε το. Το κείμενο γράφεται στο ενεργό παράθυρο.",
        does_2_title="Φωνητικές εντολές",
        does_2="Πείτε «αποθήκευση αρχείου» ή «μετάβαση στη γραμμή 40» και εκτελείται, αντί να γραφτούν οι λέξεις.",
        does_3_title="Συσκέψεις και ηχογραφήσεις",
        does_3=("Απομαγνητοφωνήστε ένα αρχείο ήχου ή καταγράψτε μια ολόκληρη σύσκεψη με "
                "σήμανση ομιλητών — όλα εκτός σύνδεσης."),
        privacy_heading="Ιδιωτικότητα",
        privacy=("Ο ήχος απομαγνητοφωνείται στον υπολογιστή σας και δεν αποστέλλεται ποτέ "
                 "πουθενά. Δεν υπάρχει τηλεμετρία ούτε διαδρομή προς το νέφος."),
        more_heading="Περισσότερα",
        more="Η υπόλοιπη τεκμηρίωση είναι προς το παρόν στα αγγλικά.",
        link_docs="Τεκμηρίωση", link_readme="Το πλήρες αγγλικό README",
        link_issues="Ζητήματα και ερωτήσεις")},

    "tr": {"name": "Türkçe", "issue": 203, "strings": _t(
        draft_title="Taslak çeviri",
        draft_body="Makine destekli ve henüz ana dili konuşan biri tarafından gözden geçirilmedi.",
        pitch=(
            "YazSes; Linux, macOS ve Windows için özgür, açık kaynaklı ve çevrimdışı "
            "çalışan bir sesli yazdırma servisidir. Bir tuşu basılı tutun, konuşun, "
            "bırakın — metin yazmakta olduğunuz yerde belirir. Her şey kendi "
            "bilgisayarınızda çalışır: bulut yok, hesap yok, abonelik yok."),
        install_heading="Kurulum", platform="Platform", command="Komut",
        any_os="Herhangi bir sistem",
        first_run=("İlk çalıştırma bir kez konuşma modelini indirir (yaklaşık 148 MB). "
                   "Sonrasında hiç ağ gerekmez."),
        does_heading="Ne yapar", does_1_title="Dikte",
        does_1="Tuşu basılı tutun, konuşun, bırakın. Metin etkin pencereye yazılır.",
        does_2_title="Sesli komutlar",
        does_2="“dosyayı kaydet” ya da “40. satıra git” deyin; sözcükleri yazmak yerine işlemi yapar.",
        does_3_title="Toplantılar ve kayıtlar",
        does_3=("Bir ses dosyasını yazıya dökün ya da tüm bir toplantıyı konuşmacı "
                "etiketleriyle kaydedin — tamamen çevrimdışı."),
        privacy_heading="Gizlilik",
        privacy=("Ses kendi bilgisayarınızda yazıya dökülür ve hiçbir yere gönderilmez. "
                 "Telemetri yoktur ve buluta giden bir yol yoktur."),
        more_heading="Dahası", more="Belgelerin geri kalanı şimdilik İngilizcedir.",
        link_docs="Belgeler", link_readme="Tam İngilizce README",
        link_issues="Sorunlar ve sorular")},

    "uk": {"name": "українська", "issue": 204, "strings": _t(
        draft_title="Чернетковий переклад",
        draft_body="Створено за допомогою машини й ще не перевірено носієм мови.",
        pitch=(
            "YazSes — вільний демон голосового введення з відкритим кодом, що працює "
            "офлайн, для Linux, macOS і Windows. Утримуйте клавішу, говоріть, відпустіть — "
            "текст з’являється там, де ви пишете. Усе виконується на вашому комп’ютері: "
            "без хмари, без облікового запису, без передплати."),
        install_heading="Встановлення", platform="Платформа", command="Команда",
        any_os="Будь-яка система",
        first_run=("Перший запуск один раз завантажує мовленнєву модель (близько 148 МБ). "
                   "Після цього мережа взагалі не потрібна."),
        does_heading="Що він робить", does_1_title="Диктування",
        does_1="Утримуйте клавішу, говоріть, відпустіть. Текст вводиться в активне вікно.",
        does_2_title="Голосові команди",
        does_2="Скажіть «зберегти файл» або «перейти до рядка 40» — і він виконає це, а не надрукує слова.",
        does_3_title="Наради та записи",
        does_3=("Розшифруйте аудіофайл або запишіть цілу нараду з позначенням мовців — "
                "усе офлайн."),
        privacy_heading="Приватність",
        privacy=("Звук розшифровується на вашому комп’ютері й ніколи нікуди не "
                 "надсилається. Немає ані телеметрії, ані шляху до хмари."),
        more_heading="Докладніше", more="Решта документації наразі англійською.",
        link_docs="Документація", link_readme="Повний README англійською",
        link_issues="Питання та звіти")},

    "ja": {"name": "日本語", "issue": 177, "strings": _t(
        draft_title="下書き翻訳",
        draft_body="機械支援による翻訳で、母語話者のレビューはまだ受けていません。",
        pitch=(
            "YazSes は Linux・macOS・Windows 向けの、無料でオープンソースの"
            "オフライン音声入力デーモンです。キーを押しながら話し、離すと、"
            "入力中の場所にそのまま文字が現れます。すべて自分のマシンで動作し、"
            "クラウドもアカウントも定額課金もありません。"),
        install_heading="インストール", platform="プラットフォーム", command="コマンド",
        any_os="任意の OS",
        first_run=("初回のみ音声モデル（約 148 MB）をダウンロードします。"
                   "その後はネットワークをまったく必要としません。"),
        does_heading="できること", does_1_title="音声入力",
        does_1="キーを押しながら話し、離します。文字はアクティブなウィンドウに入力されます。",
        does_2_title="音声コマンド",
        does_2="「ファイルを保存」「40 行目へ移動」と言えば、その言葉を入力する代わりに実行します。",
        does_3_title="会議と録音",
        does_3=("音声ファイルを文字起こししたり、会議全体を話者ラベル付きで記録したり"
                "できます。すべてオフラインです。"),
        privacy_heading="プライバシー",
        privacy=("音声はあなたのマシン上で文字起こしされ、どこにも送信されません。"
                 "テレメトリもクラウド経路もありません。"),
        more_heading="さらに詳しく", more="残りのドキュメントは現時点では英語です。",
        link_docs="ドキュメント", link_readme="英語版の完全な README",
        link_issues="課題と質問")},

    "ko": {"name": "한국어", "issue": 198, "strings": _t(
        draft_title="초안 번역",
        draft_body="기계 보조로 작성되었으며 아직 원어민의 검토를 거치지 않았습니다.",
        pitch=(
            "YazSes는 Linux, macOS, Windows용 무료 오픈소스 오프라인 음성 받아쓰기 "
            "데몬입니다. 키를 누른 채 말하고 놓으면, 입력 중이던 곳에 글자가 나타납니다. "
            "모든 처리는 사용자의 컴퓨터에서 이루어지며 클라우드도, 계정도, 구독도 "
            "필요하지 않습니다."),
        install_heading="설치", platform="플랫폼", command="명령",
        any_os="모든 운영체제",
        first_run=("처음 실행할 때 음성 모델(약 148 MB)을 한 번 내려받습니다. "
                   "그 뒤로는 네트워크가 전혀 필요하지 않습니다."),
        does_heading="할 수 있는 일", does_1_title="받아쓰기",
        does_1="키를 누른 채 말하고 놓으세요. 글자가 활성 창에 입력됩니다.",
        does_2_title="음성 명령",
        does_2="“파일 저장”이나 “40번째 줄로 이동”이라고 말하면 그 말을 적는 대신 실행합니다.",
        does_3_title="회의와 녹음",
        does_3=("오디오 파일을 받아쓰거나 회의 전체를 화자 표시와 함께 기록할 수 "
                "있습니다. 모두 오프라인입니다."),
        privacy_heading="개인정보",
        privacy=("음성은 사용자의 컴퓨터에서 처리되며 어디에도 전송되지 않습니다. "
                 "원격 측정도, 클라우드 경로도 없습니다."),
        more_heading="더 보기", more="나머지 문서는 현재 영어로 되어 있습니다.",
        link_docs="문서", link_readme="영어 전체 README",
        link_issues="이슈와 질문")},

    "id": {"name": "bahasa Indonesia", "issue": 179, "strings": _t(
        draft_title="Terjemahan draf",
        draft_body="Dibantu mesin dan belum ditinjau oleh penutur asli.",
        pitch=(
            "YazSes adalah daemon dikte suara yang bebas, sumber terbuka, dan bekerja "
            "luring untuk Linux, macOS, dan Windows. Tahan sebuah tombol, bicaralah, lalu "
            "lepaskan — teksnya muncul di tempat Anda sedang mengetik. Semuanya berjalan "
            "di komputer Anda sendiri: tanpa awan, tanpa akun, tanpa langganan."),
        install_heading="Pemasangan", platform="Platform", command="Perintah",
        any_os="Sistem apa pun",
        first_run=("Jalankan pertama kali akan mengunduh model suara satu kali (sekitar "
                   "148 MB). Setelah itu sama sekali tidak memerlukan jaringan."),
        does_heading="Apa yang dilakukannya", does_1_title="Dikte",
        does_1="Tahan tombolnya, bicaralah, lepaskan. Teks diketikkan ke jendela yang aktif.",
        does_2_title="Perintah suara",
        does_2="Ucapkan “simpan berkas” atau “ke baris 40”, dan ia bertindak alih-alih mengetik kata-katanya.",
        does_3_title="Rapat dan rekaman",
        does_3=("Transkripsikan berkas audio, atau rekam seluruh rapat dengan penandaan "
                "pembicara — semuanya luring."),
        privacy_heading="Privasi",
        privacy=("Audio ditranskripsikan di komputer Anda dan tidak pernah dikirim ke mana "
                 "pun. Tidak ada telemetri dan tidak ada jalur ke awan."),
        more_heading="Selengkapnya", more="Dokumentasi selebihnya untuk saat ini berbahasa Inggris.",
        link_docs="Dokumentasi", link_readme="README lengkap dalam bahasa Inggris",
        link_issues="Isu dan pertanyaan")},

    "vi": {"name": "Tiếng Việt", "issue": 205, "strings": _t(
        draft_title="Bản dịch nháp",
        draft_body="Được máy hỗ trợ và chưa qua rà soát của người bản ngữ.",
        pitch=(
            "YazSes là một dịch vụ đọc chính tả bằng giọng nói, miễn phí, mã nguồn mở và "
            "chạy ngoại tuyến trên Linux, macOS và Windows. Giữ một phím, nói, rồi thả ra — "
            "văn bản hiện ra ngay nơi bạn đang gõ. Mọi thứ chạy trên máy của bạn: không "
            "đám mây, không tài khoản, không thuê bao."),
        install_heading="Cài đặt", platform="Nền tảng", command="Lệnh",
        any_os="Mọi hệ điều hành",
        first_run=("Lần chạy đầu tiên tải về một mô hình giọng nói (khoảng 148 MB). "
                   "Sau đó hoàn toàn không cần mạng."),
        does_heading="Nó làm được gì", does_1_title="Đọc chính tả",
        does_1="Giữ phím, nói, thả ra. Văn bản được gõ vào cửa sổ đang hoạt động.",
        does_2_title="Lệnh thoại",
        does_2="Nói “lưu tệp” hoặc “tới dòng 40” và nó thực hiện, thay vì gõ ra những chữ đó.",
        does_3_title="Cuộc họp và bản ghi",
        does_3=("Chuyển một tệp âm thanh thành văn bản, hoặc ghi lại cả cuộc họp kèm nhãn "
                "người nói — tất cả đều ngoại tuyến."),
        privacy_heading="Quyền riêng tư",
        privacy=("Âm thanh được chuyển thành văn bản ngay trên máy bạn và không bao giờ "
                 "được gửi đi đâu. Không có đo từ xa và không có đường ra đám mây."),
        more_heading="Thêm nữa", more="Phần tài liệu còn lại hiện vẫn bằng tiếng Anh.",
        link_docs="Tài liệu", link_readme="README đầy đủ bằng tiếng Anh",
        link_issues="Vấn đề và câu hỏi")},

    "th": {"name": "ไทย", "issue": 231, "strings": _t(
        draft_title="ฉบับร่างของคำแปล",
        draft_body="แปลโดยมีเครื่องช่วย และยังไม่ได้ตรวจทานโดยเจ้าของภาษา",
        pitch=(
            "YazSes คือเดมอนสำหรับพิมพ์ด้วยเสียงที่ฟรี โอเพนซอร์ส และทำงานแบบออฟไลน์ "
            "บน Linux, macOS และ Windows กดปุ่มค้างไว้ พูด แล้วปล่อย ข้อความจะปรากฏ "
            "ตรงที่คุณกำลังพิมพ์อยู่ ทุกอย่างทำงานบนเครื่องของคุณเอง ไม่มีคลาวด์ "
            "ไม่ต้องมีบัญชี และไม่มีค่าสมาชิก"),
        install_heading="การติดตั้ง", platform="แพลตฟอร์ม", command="คำสั่ง",
        any_os="ระบบปฏิบัติการใดก็ได้",
        first_run=("การเรียกใช้ครั้งแรกจะดาวน์โหลดโมเดลเสียงหนึ่งครั้ง (ประมาณ 148 MB) "
                   "หลังจากนั้นไม่ต้องใช้เครือข่ายเลย"),
        does_heading="ทำอะไรได้บ้าง", does_1_title="การพิมพ์ด้วยเสียง",
        does_1="กดปุ่มค้างไว้ พูด แล้วปล่อย ข้อความจะถูกพิมพ์ลงในหน้าต่างที่กำลังใช้งาน",
        does_2_title="คำสั่งเสียง",
        does_2="พูดว่า “บันทึกไฟล์” หรือ “ไปที่บรรทัด 40” แล้วมันจะทำให้ แทนที่จะพิมพ์คำเหล่านั้น",
        does_3_title="การประชุมและไฟล์บันทึก",
        does_3=("ถอดความไฟล์เสียง หรือบันทึกการประชุมทั้งครั้งพร้อมป้ายชื่อผู้พูด "
                "ทั้งหมดนี้ทำแบบออฟไลน์"),
        privacy_heading="ความเป็นส่วนตัว",
        privacy=("เสียงจะถูกถอดความบนเครื่องของคุณและไม่เคยถูกส่งไปที่ใด "
                 "ไม่มีการเก็บข้อมูลการใช้งานและไม่มีเส้นทางไปยังคลาวด์"),
        more_heading="เพิ่มเติม", more="เอกสารส่วนที่เหลือยังเป็นภาษาอังกฤษในขณะนี้",
        link_docs="เอกสาร", link_readme="README ฉบับเต็มภาษาอังกฤษ",
        link_issues="ปัญหาและคำถาม")},

    "zh-TW": {"name": "繁體中文", "issue": 192, "strings": _t(
        draft_title="翻譯草稿",
        draft_body="由機器協助翻譯，尚未經母語人士校閱。",
        pitch=(
            "YazSes 是一套自由、開放原始碼且離線運作的語音聽寫服務，支援 Linux、macOS "
            "與 Windows。按住一個按鍵、開口說話、放開按鍵，文字就會出現在你正在輸入的"
            "地方。所有處理都在你自己的電腦上完成：不需雲端、不需帳號、不需訂閱。"),
        install_heading="安裝", platform="平台", command="指令",
        any_os="任何作業系統",
        first_run=("第一次執行會下載一次語音模型（約 148 MB）。之後完全不需要網路。"),
        does_heading="它能做什麼", does_1_title="語音聽寫",
        does_1="按住按鍵、說話、放開。文字會輸入到目前作用中的視窗。",
        does_2_title="語音指令",
        does_2="說「儲存檔案」或「跳到第 40 行」，它會直接執行，而不是把這些字打出來。",
        does_3_title="會議與錄音",
        does_3=("把音訊檔轉成文字，或錄下整場會議並標示發言者，全部離線完成。"),
        privacy_heading="隱私",
        privacy=("音訊在你自己的電腦上轉寫，永遠不會傳送到任何地方。沒有遙測，也沒有"
                 "任何通往雲端的路徑。"),
        more_heading="更多", more="其餘文件目前為英文。",
        link_docs="說明文件", link_readme="完整的英文 README",
        link_issues="問題與提問")},

    "bn": {"name": "বাংলা", "issue": 191, "strings": _t(
        draft_title="খসড়া অনুবাদ",
        draft_body="যন্ত্রসহায়তায় তৈরি, এখনও কোনো মাতৃভাষীর দ্বারা পর্যালোচিত নয়।",
        pitch=(
            "YazSes হলো Linux, macOS ও Windows-এর জন্য একটি বিনামূল্যের, মুক্ত উৎসের ও "
            "অফলাইন ভয়েস-ডিকটেশন ডিমন। একটি কী চেপে ধরুন, বলুন, ছেড়ে দিন — আপনি যেখানে "
            "লিখছেন সেখানেই লেখাটি এসে যাবে। সবকিছু আপনার নিজের কম্পিউটারে চলে: কোনো "
            "ক্লাউড নয়, কোনো অ্যাকাউন্ট নয়, কোনো সাবস্ক্রিপশন নয়।"),
        install_heading="ইনস্টল", platform="প্ল্যাটফর্ম", command="কমান্ড",
        any_os="যেকোনো সিস্টেম",
        first_run=("প্রথমবার চালালে একবারই একটি স্পিচ মডেল নামানো হয় (প্রায় ১৪৮ MB)। "
                   "তারপর আর কোনো নেটওয়ার্কের দরকার হয় না।"),
        does_heading="এটি যা করে", does_1_title="ডিকটেশন",
        does_1="কী চেপে ধরুন, বলুন, ছেড়ে দিন। লেখাটি সক্রিয় উইন্ডোতে টাইপ হয়ে যায়।",
        does_2_title="ভয়েস কমান্ড",
        does_2="“ফাইল সেভ করো” বা “৪০ নম্বর লাইনে যাও” বললে সে কথাগুলো না লিখে কাজটাই করে।",
        does_3_title="মিটিং ও রেকর্ডিং",
        does_3=("একটি অডিও ফাইল প্রতিলিপি করুন, বা পুরো মিটিং রেকর্ড করুন কে কী বলল তার "
                "চিহ্নসহ — সবই অফলাইনে।"),
        privacy_heading="গোপনীয়তা",
        privacy=("অডিও আপনার কম্পিউটারেই লেখায় রূপান্তরিত হয় এবং কোথাও পাঠানো হয় না। "
                 "কোনো টেলিমেট্রি নেই, ক্লাউডে যাওয়ার কোনো পথও নেই।"),
        more_heading="আরও", more="বাকি নথিপত্র আপাতত ইংরেজিতে।",
        link_docs="নথিপত্র", link_readme="সম্পূর্ণ ইংরেজি README",
        link_issues="সমস্যা ও প্রশ্ন")},

    "ta": {"name": "தமிழ்", "issue": 202, "strings": _t(
        draft_title="வரைவு மொழிபெயர்ப்பு",
        draft_body="இயந்திர உதவியுடன் செய்யப்பட்டது; தாய்மொழி பேசுபவரால் இன்னும் சரிபார்க்கப்படவில்லை.",
        pitch=(
            "YazSes என்பது Linux, macOS மற்றும் Windows-க்கான கட்டணமில்லாத, திறந்த மூல, "
            "இணையம் இல்லாமல் இயங்கும் குரல் எழுத்தாக்க சேவை. ஒரு விசையை அழுத்திப் பிடித்து, "
            "பேசி, விடுங்கள் — நீங்கள் தட்டச்சு செய்யும் இடத்திலேயே உரை தோன்றும். அனைத்தும் "
            "உங்கள் கணினியிலேயே இயங்குகிறது: மேகக்கணி இல்லை, கணக்கு இல்லை, சந்தா இல்லை."),
        install_heading="நிறுவல்", platform="தளம்", command="கட்டளை",
        any_os="எந்த இயங்குதளமும்",
        first_run=("முதல் முறை இயக்கும்போது ஒரு பேச்சு மாதிரி (சுமார் 148 MB) ஒருமுறை "
                   "பதிவிறக்கப்படும். அதன்பிறகு இணையமே தேவையில்லை."),
        does_heading="இது என்ன செய்கிறது", does_1_title="குரல் எழுத்தாக்கம்",
        does_1="விசையை அழுத்திப் பிடித்து, பேசி, விடுங்கள். உரை செயலில் உள்ள சாளரத்தில் தட்டச்சாகும்.",
        does_2_title="குரல் கட்டளைகள்",
        does_2="“கோப்பைச் சேமி” அல்லது “வரி 40-க்குச் செல்” எனச் சொன்னால், அச்சொற்களைத் தட்டச்சு செய்யாமல் அதைச் செய்யும்.",
        does_3_title="கூட்டங்களும் பதிவுகளும்",
        does_3=("ஒரு ஒலிக் கோப்பை உரையாக்கலாம், அல்லது முழுக் கூட்டத்தையும் யார் பேசினார் "
                "என்ற குறியீட்டுடன் பதிவு செய்யலாம் — அனைத்தும் இணையம் இல்லாமல்."),
        privacy_heading="தனியுரிமை",
        privacy=("ஒலி உங்கள் கணினியிலேயே உரையாக மாற்றப்படுகிறது; எங்கும் அனுப்பப்படுவதில்லை. "
                 "தொலைஅளவீடு இல்லை, மேகக்கணிக்கான பாதையும் இல்லை."),
        more_heading="மேலும்", more="மீதமுள்ள ஆவணங்கள் தற்போதைக்கு ஆங்கிலத்தில் உள்ளன.",
        link_docs="ஆவணங்கள்", link_readme="முழு ஆங்கில README",
        link_issues="சிக்கல்களும் கேள்விகளும்")},

    "te": {"name": "తెలుగు", "issue": 230, "strings": _t(
        draft_title="ముసాయిదా అనువాదం",
        draft_body="యంత్ర సహాయంతో చేసినది; ఇంకా మాతృభాషీయుల సమీక్షకు నోచుకోలేదు.",
        pitch=(
            "YazSes అనేది Linux, macOS మరియు Windows కోసం ఉచిత, ఓపెన్ సోర్స్, ఆఫ్‌లైన్ "
            "వాయిస్ డిక్టేషన్ సేవ. ఒక కీని నొక్కి పట్టుకుని మాట్లాడి వదిలేయండి — మీరు "
            "టైప్ చేస్తున్న చోటే వచనం కనిపిస్తుంది. అంతా మీ కంప్యూటర్‌లోనే జరుగుతుంది: "
            "క్లౌడ్ లేదు, ఖాతా లేదు, చందా లేదు."),
        install_heading="ఇన్‌స్టాల్", platform="ప్లాట్‌ఫారమ్", command="ఆదేశం",
        any_os="ఏ ఆపరేటింగ్ సిస్టమ్ అయినా",
        first_run=("మొదటిసారి నడిపినప్పుడు ఒకసారి మాత్రమే స్పీచ్ మోడల్ (సుమారు 148 MB) "
                   "డౌన్‌లోడ్ అవుతుంది. ఆ తర్వాత నెట్‌వర్క్ అవసరమే లేదు."),
        does_heading="ఇది ఏమి చేస్తుంది", does_1_title="డిక్టేషన్",
        does_1="కీని నొక్కి పట్టుకుని మాట్లాడి వదిలేయండి. వచనం క్రియాశీల విండోలో టైప్ అవుతుంది.",
        does_2_title="వాయిస్ ఆదేశాలు",
        does_2="“ఫైల్ సేవ్ చెయ్యి” లేదా “40వ లైన్‌కి వెళ్ళు” అంటే ఆ మాటలు రాయకుండా పనిని చేస్తుంది.",
        does_3_title="సమావేశాలు మరియు రికార్డింగ్‌లు",
        does_3=("ఆడియో ఫైల్‌ను వచనంగా మార్చండి, లేదా ఎవరు మాట్లాడారో గుర్తులతో సహా "
                "మొత్తం సమావేశాన్ని రికార్డ్ చేయండి — అంతా ఆఫ్‌లైన్‌లోనే."),
        privacy_heading="గోప్యత",
        privacy=("ఆడియో మీ కంప్యూటర్‌లోనే వచనంగా మారుతుంది, ఎక్కడికీ పంపబడదు. "
                 "టెలిమెట్రీ లేదు, క్లౌడ్‌కు దారీ లేదు."),
        more_heading="ఇంకా", more="మిగిలిన పత్రాలు ప్రస్తుతానికి ఇంగ్లీషులో ఉన్నాయి.",
        link_docs="పత్రాలు", link_readme="పూర్తి ఇంగ్లీష్ README",
        link_issues="సమస్యలు మరియు ప్రశ్నలు")},

    "ar": {"name": "العربية", "issue": 190, "rtl": True, "strings": _t(
        draft_title="ترجمة أولية",
        draft_body="أُنجزت بمساعدة آلية ولم يراجعها بعدُ ناطق أصلي باللغة.",
        pitch=(
            "‏YazSes خدمة إملاء صوتي حرة ومفتوحة المصدر تعمل دون اتصال بالإنترنت على "
            "Linux وmacOS وWindows. اضغط مفتاحًا مع الاستمرار، تكلّم، ثم اترك المفتاح — "
            "فيظهر النص في المكان الذي تكتب فيه. كل شيء يعمل على جهازك: بلا سحابة، "
            "وبلا حساب، وبلا اشتراك."),
        install_heading="التثبيت", platform="النظام", command="الأمر",
        any_os="أي نظام تشغيل",
        first_run=("يُنزّل التشغيل الأول نموذج الكلام مرة واحدة (نحو 148 ميغابايت). "
                   "بعد ذلك لا يحتاج إلى شبكة إطلاقًا."),
        does_heading="ماذا يفعل", does_1_title="الإملاء",
        does_1="اضغط المفتاح مع الاستمرار، تكلّم، ثم اتركه. يُكتب النص في النافذة النشطة.",
        does_2_title="الأوامر الصوتية",
        does_2="قل «احفظ الملف» أو «اذهب إلى السطر 40» فينفّذ ذلك بدل كتابة الكلمات.",
        does_3_title="الاجتماعات والتسجيلات",
        does_3=("فرِّغ ملفًا صوتيًا إلى نص، أو سجّل اجتماعًا كاملًا مع تمييز المتحدثين — "
                "كل ذلك دون اتصال."),
        privacy_heading="الخصوصية",
        privacy=("يُفرَّغ الصوت على جهازك ولا يُرسل إلى أي مكان. لا توجد قياسات عن بُعد "
                 "ولا أي مسار إلى السحابة."),
        more_heading="المزيد", more="بقية التوثيق بالإنجليزية في الوقت الحالي.",
        link_docs="التوثيق", link_readme="ملف README الإنجليزي الكامل",
        link_issues="المشكلات والأسئلة")},

    "fa": {"name": "فارسی", "issue": 199, "rtl": True, "strings": _t(
        draft_title="ترجمهٔ پیش‌نویس",
        draft_body="با کمک ماشین انجام شده و هنوز یک فارسی‌زبان بومی آن را بازبینی نکرده است.",
        pitch=(
            "‏YazSes یک سرویس آزاد و متن‌باز برای دیکتهٔ صوتی است که به‌صورت آفلاین روی "
            "Linux و macOS و Windows کار می‌کند. یک کلید را نگه دارید، حرف بزنید و رها "
            "کنید — متن همان‌جا که در حال تایپ هستید ظاهر می‌شود. همه‌چیز روی رایانهٔ "
            "خودتان اجرا می‌شود: بدون ابر، بدون حساب کاربری و بدون اشتراک."),
        install_heading="نصب", platform="سکو", command="فرمان",
        any_os="هر سیستم‌عاملی",
        first_run=("اجرای نخست یک بار مدل گفتار (حدود ۱۴۸ مگابایت) را دانلود می‌کند. "
                   "پس از آن اصلاً به شبکه نیازی ندارد."),
        does_heading="چه کاری انجام می‌دهد", does_1_title="دیکته",
        does_1="کلید را نگه دارید، حرف بزنید و رها کنید. متن در پنجرهٔ فعال تایپ می‌شود.",
        does_2_title="فرمان‌های صوتی",
        does_2="بگویید «فایل را ذخیره کن» یا «برو به خط ۴۰»، و به‌جای نوشتن این کلمه‌ها همان کار را انجام می‌دهد.",
        does_3_title="جلسه‌ها و ضبط‌ها",
        does_3=("یک فایل صوتی را پیاده‌سازی کنید، یا کل یک جلسه را همراه با مشخص‌کردن "
                "گویندگان ضبط کنید — همه به‌صورت آفلاین."),
        privacy_heading="حریم خصوصی",
        privacy=("صدا روی رایانهٔ خودتان به متن تبدیل می‌شود و هرگز به جایی فرستاده "
                 "نمی‌شود. نه تله‌متری وجود دارد و نه هیچ مسیری به ابر."),
        more_heading="بیشتر", more="بقیهٔ مستندات فعلاً به انگلیسی است.",
        link_docs="مستندات", link_readme="‏README کامل انگلیسی",
        link_issues="مسائل و پرسش‌ها")},

    "he": {"name": "עברית", "issue": 196, "rtl": True, "strings": _t(
        draft_title="תרגום טיוטה",
        draft_body="נעשה בעזרת מכונה ועדיין לא נבדק בידי דובר שפת אם.",
        pitch=(
            "‏YazSes הוא שירות הכתבה קולית חופשי, בקוד פתוח, שפועל ללא חיבור לאינטרנט "
            "ב-Linux, ב-macOS וב-Windows. החזיקו מקש, דברו ושחררו — הטקסט מופיע בדיוק "
            "במקום שבו אתם מקלידים. הכול רץ במחשב שלכם: בלי ענן, בלי חשבון ובלי מנוי."),
        install_heading="התקנה", platform="פלטפורמה", command="פקודה",
        any_os="כל מערכת הפעלה",
        first_run=("ההרצה הראשונה מורידה פעם אחת מודל דיבור (כ-148 מ״ב). לאחר מכן אין "
                   "צורך ברשת כלל."),
        does_heading="מה הוא עושה", does_1_title="הכתבה",
        does_1="החזיקו את המקש, דברו ושחררו. הטקסט מוקלד לחלון הפעיל.",
        does_2_title="פקודות קוליות",
        does_2="אמרו „שמור קובץ” או „עבור לשורה 40”, והוא יבצע זאת במקום להקליד את המילים.",
        does_3_title="פגישות והקלטות",
        does_3=("תמללו קובץ שמע, או הקליטו פגישה שלמה עם סימון מי דיבר — הכול ללא חיבור."),
        privacy_heading="פרטיות",
        privacy=("השמע מתומלל במחשב שלכם ולעולם אינו נשלח לשום מקום. אין טלמטריה ואין "
                 "שום נתיב לענן."),
        more_heading="עוד", more="שאר התיעוד באנגלית בשלב זה.",
        link_docs="תיעוד", link_readme="‏README המלא באנגלית",
        link_issues="תקלות ושאלות")},

    "ur": {"name": "اردو", "issue": 232, "rtl": True, "strings": _t(
        draft_title="مسودۂ ترجمہ",
        draft_body="مشین کی مدد سے کیا گیا ہے اور ابھی کسی مادری بولنے والے نے اس پر نظرثانی نہیں کی۔",
        pitch=(
            "‏YazSes ایک مفت، اوپن سورس اور آف لائن آواز سے لکھنے والی سروس ہے جو Linux، "
            "macOS اور Windows پر چلتی ہے۔ ایک کلید دبائے رکھیں، بولیں، اور چھوڑ دیں — "
            "متن وہیں آ جاتا ہے جہاں آپ لکھ رہے ہیں۔ سب کچھ آپ ہی کے کمپیوٹر پر چلتا ہے: "
            "نہ کلاؤڈ، نہ اکاؤنٹ، نہ سبسکرپشن۔"),
        install_heading="تنصیب", platform="پلیٹ فارم", command="کمانڈ",
        any_os="کوئی بھی نظام",
        first_run=("پہلی بار چلانے پر ایک بار تقریر کا ماڈل (تقریباً 148 MB) ڈاؤن لوڈ "
                   "ہوتا ہے۔ اس کے بعد نیٹ ورک کی بالکل ضرورت نہیں رہتی۔"),
        does_heading="یہ کیا کرتا ہے", does_1_title="املا",
        does_1="کلید دبائے رکھیں، بولیں، چھوڑ دیں۔ متن فعال ونڈو میں لکھا جاتا ہے۔",
        does_2_title="آوازی کمانڈز",
        does_2="کہیے «فائل محفوظ کرو» یا «لائن 40 پر جاؤ» — یہ الفاظ لکھنے کے بجائے کام کر دے گا۔",
        does_3_title="میٹنگز اور ریکارڈنگز",
        does_3=("کسی آڈیو فائل کو متن میں بدلیں، یا پوری میٹنگ بولنے والوں کی نشاندہی کے "
                "ساتھ ریکارڈ کریں — سب آف لائن۔"),
        privacy_heading="رازداری",
        privacy=("آواز آپ ہی کے کمپیوٹر پر متن میں بدلتی ہے اور کبھی کہیں نہیں بھیجی جاتی۔ "
                 "نہ کوئی ٹیلی میٹری ہے اور نہ کلاؤڈ تک کوئی راستہ۔"),
        more_heading="مزید", more="باقی دستاویزات فی الحال انگریزی میں ہیں۔",
        link_docs="دستاویزات", link_readme="مکمل انگریزی README",
        link_issues="مسائل اور سوالات")},

    "ru-note": {"name": "", "issue": 0, "strings": _EN},  # placeholder, removed below
}

LOCALES.pop("ru-note", None)

# Human translations that already exist as files. The generator must NEVER write
# these — overwriting a contributor's writing with machine output is the one thing
# the localisation tooling exists to avoid — but the language switcher has to list
# them, or adding a generated locale silently drops them from every README.
HUMAN_LOCALES: dict[str, str] = {
    "hi": "हिंदी",
    "ru": "Русский",
    "zh-CN": "简体中文",
}
