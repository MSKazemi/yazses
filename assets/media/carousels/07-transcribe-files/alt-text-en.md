# 07-transcribe-files — alt text (paste per slide in Instagram → Advanced settings → Accessibility)

01. Transcribe any recording offline: interviews, lectures, podcasts. Nothing uploaded.
02. One command: yazses transcribe interview.m4a writes interview.txt next to it.
03. Choose the output format: txt, md, srt, vtt or json. srt and vtt include timestamps for subtitles.
04. Who said what: --diarize labels each speaker using local models, about 45 MB downloaded once.
05. Better accuracy per run with --model small.en. With a multilingual model, --language translate turns non-English audio into English text.
06. No install needed: run the published Docker image, and add --network none to prove the transcription happens on your machine.
07. Your recordings stay yours. Docs at mskazemi.com/yazses, code at github.com/MSKazemi/yazses. Free, Apache-2.0, offline. QR code (Tutorial): https://mskazemi.com/yazses/tutorials/transcribe-recordings.html.
