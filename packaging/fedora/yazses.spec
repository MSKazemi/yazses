# RPM spec for YazSes — Fedora / RHEL family, built for COPR (#77).
#
# WHY THIS BUNDLES ITS DEPENDENCIES
#
# The idiomatic Fedora spec uses %%pyproject_wheel + %%pyproject_install and lets
# the macros generate `python3dist(...)` requires. That needs every runtime
# dependency to exist in the Fedora repositories, and the ones that matter here do
# not: faster-whisper, ctranslate2 and onnx-asr are not packaged, and ctranslate2
# is a compiled wheel with no Fedora build. A %%pyproject spec would fail
# dependency generation on a clean mock, which is a worse outcome than an honest
# bundle.
#
# So this installs into a private virtualenv under %%{_libdir}/yazses and exposes
# the console scripts through %%{_bindir}. That is acceptable for a COPR and is
# NOT acceptable for the official Fedora repositories — getting there means
# packaging the dependency tree first, which is the "stretch" in the issue and a
# much larger job than this file.
#
# Build and test it exactly the way CI does:
#   podman run --rm -v "$PWD:/src:z" fedora:41 /src/packaging/fedora/build-and-test.sh

%global appname yazses
%global venvdir %{_libdir}/%{appname}
# The bundled virtualenv contains prebuilt binaries; do not try to generate
# provides/requires from them, and do not mangle their shebangs.
%global __requires_exclude_from ^%{venvdir}/.*$
%global __provides_exclude_from ^%{venvdir}/.*$
%global __brp_mangle_shebangs_exclude_from ^%{venvdir}/.*$
%global debug_package %{nil}

Name:           %{appname}
Version:        2.18.2
Release:        1%{?dist}
Summary:        Offline hold-to-talk voice dictation and speech-to-text

License:        Apache-2.0
URL:            https://github.com/MSKazemi/yazses
Source0:        %{pypi_source yazses}

BuildRequires:  python3-devel >= 3.11
BuildRequires:  python3-pip
BuildRequires:  gcc
BuildRequires:  kernel-headers
# evdev — the hold-to-talk key reader — publishes no wheels at all, so it is
# compiled here. Without these it fails at pip time with a missing linux/input.h.

Requires:       python3 >= 3.11
Requires:       portaudio

# Injection tooling. Recommends rather than Requires: a user transcribing files
# with `yazses transcribe` needs none of it, and a hard dependency would pull an
# X11 stack onto a headless machine.
Recommends:     xdotool
Recommends:     xclip
Suggests:       ydotool
Suggests:       wl-clipboard

%description
YazSes is an offline voice dictation daemon. Hold a key, speak, release — the
text is typed into whatever window has focus. Transcription runs on your own
CPU with faster-whisper; there is no cloud, no account and no subscription.

It also transcribes existing audio files and captures whole meetings with
speaker labels, entirely on-device.

After installing, run `yazses doctor` — it reports what this machine still
needs, including membership of the `input` group, which hold-to-talk requires
and which takes effect only after a full logout.

%prep
%autosetup -n yazses-%{version}

%build
# Nothing to build here: the virtualenv is populated in %%install, because pip
# needs the final prefix to write correct console scripts.

%install
python3 -m venv %{buildroot}%{venvdir}
# --no-warn-script-location: the scripts land under the buildroot, which is not
# on PATH by definition, and the warning is noise in every build log.
%{buildroot}%{venvdir}/bin/python -m pip install --upgrade pip --no-warn-script-location
%{buildroot}%{venvdir}/bin/python -m pip install . --no-warn-script-location

# The venv records the buildroot path in its scripts and pyvenv.cfg. Rewrite both
# to the installed location, or every console script points at a directory that
# only existed during the build.
sed -i "s|%{buildroot}||g" %{buildroot}%{venvdir}/bin/* %{buildroot}%{venvdir}/pyvenv.cfg
find %{buildroot}%{venvdir}/bin -type l -delete
ln -sf %{venvdir}/bin/python3 %{buildroot}%{venvdir}/bin/python
ln -sf %{venvdir}/bin/python3 %{buildroot}%{venvdir}/bin/python3.

install -d %{buildroot}%{_bindir}
for script in yazses yazses-daemon yazses-tray yazses-agent yazses-overlay; do
    ln -sf %{venvdir}/bin/$script %{buildroot}%{_bindir}/$script
done

# Desktop launcher and icons, the same files the .deb installs (#59).
install -Dm644 packaging/../contrib/yazses-settings.desktop \
    %{buildroot}%{_datadir}/applications/yazses-settings.desktop 2>/dev/null || :
install -Dm644 contrib/icons/yazses.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/yazses.svg 2>/dev/null || :

%files
%license LICENSE
%doc README.md
%{venvdir}
%{_bindir}/yazses
%{_bindir}/yazses-daemon
%{_bindir}/yazses-tray
%{_bindir}/yazses-agent
%{_bindir}/yazses-overlay
%{_datadir}/applications/yazses-settings.desktop
%{_datadir}/icons/hicolor/scalable/apps/yazses.svg

%changelog
* Thu Aug 14 2026 Mohsen Seyedkazemi Ardebili <mohsen.seyedkazemi@gmail.com> - 2.18.2-1
- Initial COPR package.
