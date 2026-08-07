# Shared runtime environment for every yazses snap app.
#
# Sourced (never executed) by the four app wrappers, so a path fix lands in all
# of them at once instead of being copy-pasted four times and drifting.

# snapd exports SNAP_ARCH as the snap's architecture; map it to the Debian
# multiarch triplet the staged libraries actually live under.
#
# This used to be the literal string "x86_64-linux-gnu" in four wrappers and in
# the apps' environment: blocks. That is invisible on amd64 and fatal anywhere
# else -- the ALSA pulse plugin and the PulseAudio libraries sit beneath the
# triplet directory, so on a non-amd64 build the paths simply resolve to nothing
# and microphone capture dies with no error the user could act on.
case "${SNAP_ARCH:-}" in
  amd64)   YAZSES_TRIPLET=x86_64-linux-gnu ;;
  arm64)   YAZSES_TRIPLET=aarch64-linux-gnu ;;
  armhf)   YAZSES_TRIPLET=arm-linux-gnueabihf ;;
  ppc64el) YAZSES_TRIPLET=powerpc64le-linux-gnu ;;
  s390x)   YAZSES_TRIPLET=s390x-linux-gnu ;;
  riscv64) YAZSES_TRIPLET=riscv64-linux-gnu ;;
  i386)    YAZSES_TRIPLET=i386-linux-gnu ;;
  *)       YAZSES_TRIPLET="$(uname -m)-linux-gnu" ;;
esac
export YAZSES_TRIPLET

export PYTHONPATH="$SNAP/lib/python3.12/site-packages:${PYTHONPATH:-}"
export PATH="$SNAP/bin:$SNAP/usr/bin:$PATH"

# Audio environment for the apps that open the microphone (yazses, yazses-daemon).
#
# Set here rather than in snapcraft.yaml's apps.*.environment because both ALSA
# paths are arch-dependent and that block cannot expand the triplet.
yazses_audio_env() {
  # The snap's private XDG_RUNTIME_DIR has no pulse socket, so point at the
  # host's -- reachable under the audio-record interface.
  export PULSE_SERVER="${PULSE_SERVER:-unix:/run/user/$(id -u)/pulse/native}"
  export LD_LIBRARY_PATH="$SNAP/usr/lib/$YAZSES_TRIPLET/pulseaudio:${LD_LIBRARY_PATH:-}"
  # Give libasound a config the confined snap can actually read (it cannot see
  # the host's /usr/share/alsa), so PortAudio's Pa_Initialize routes through
  # PulseAudio instead of aborting. See snap/local/asound.conf.
  export ALSA_CONFIG_PATH="$SNAP/etc/asound.conf"
  export ALSA_PLUGIN_DIR="$SNAP/usr/lib/$YAZSES_TRIPLET/alsa-lib"
}
