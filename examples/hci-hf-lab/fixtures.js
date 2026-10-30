window.HCI_FIXTURES = {
  "schema_version": "1.0",
  "synthetic": true,
  "license": "Apache-2.0",
  "provenance": "Hand-authored scenario definitions for a research prototype. No human participant, sensor recording, audio, image, transcript or user data was collected or used. Every confidence, age and duration is a simulated, illustrative number.",
  "generator": "hand-authored; no random seed",
  "notice": "Schema 1.0, maintained in examples/hci-hf-lab/ (issue #699). Every confidence, age and duration is a simulated, illustrative number.",
  "thresholds": {
    "gaze_min_confidence": 0.6,
    "max_age_ms": 500,
    "voice_min_confidence": 0.6,
    "activation_min_confidence": { "blink": 0.7, "face_gesture": 0.7, "emg_hold": 0.8, "eeg_eog": 0.9 },
    "emg_min_hold_ms": 250,
    "blink_refractory_ms": 400,
    "ambiguity_margin_pct": 5
  },
  "desktop": {
    "windows": [
      { "id": "notes", "label": "Notes", "rect": { "x": 4, "y": 6, "w": 44, "h": 50 }, "trusted": true },
      { "id": "terminal", "label": "Terminal", "rect": { "x": 52, "y": 6, "w": 44, "h": 50 }, "trusted": true },
      { "id": "mail", "label": "Mail", "rect": { "x": 4, "y": 62, "w": 60, "h": 32 }, "trusted": true },
      {
        "id": "browser",
        "label": "Browser (unverified page)",
        "rect": { "x": 68, "y": 62, "w": 28, "h": 32 },
        "trusted": false
      }
    ]
  },
  "intents": [
    { "id": "open", "label": "Open", "destructive": false },
    { "id": "close", "label": "Close", "destructive": false },
    { "id": "copy", "label": "Copy", "destructive": false },
    { "id": "delete", "label": "Delete", "destructive": true },
    { "id": "send", "label": "Send", "destructive": true },
    { "id": "stop", "label": "Stop", "destructive": false }
  ],
  "activation_kinds": [
    { "id": "none", "label": "None", "experimental": false },
    { "id": "blink", "label": "Deliberate blink", "experimental": false },
    { "id": "face_gesture", "label": "Face gesture", "experimental": false },
    { "id": "emg_hold", "label": "EMG hold", "experimental": false },
    { "id": "eeg_eog", "label": "EEG/EOG event [EXPERIMENTAL]", "experimental": true }
  ],
  "scenarios": [
    {
      "id": "correct_target",
      "title": "Correct target",
      "description": "Gaze rests on Notes with high confidence, the spoken intent names no target, and a deliberate blink follows. The proposal targets Notes.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.92, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "open", "target": "notes", "outcome": "previewed" }
    },
    {
      "id": "low_confidence",
      "title": "Low gaze confidence",
      "description": "Gaze confidence is 0.35, below the 0.6 floor, and voice names no target. The resolver abstains and points to the keyboard or a spoken target.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated dim room", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 880, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.35, "age_ms": 120, "quality": "degraded" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "stale_sensor",
      "title": "Stale sensor sample",
      "description": "The only gaze sample is 900 ms old, over the 500 ms limit. A stale point is never trusted; the resolver abstains.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "terminal",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, dropped frames" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 100, "source": "gaze", "event": "sample" },
        { "seq": 3, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.9, "age_ms": 900, "quality": "degraded" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "conflicting_modalities",
      "title": "Conflicting modalities",
      "description": "Gaze is on Terminal with good confidence but the user says 'open mail'. The two modalities disagree, so the resolver abstains and asks for one clear target.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "mail",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.9, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": "mail" },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "muscle_hold_release",
      "title": "Muscle hold released early",
      "description": "Negative example. The EMG hold is released after 120 ms; at least 250 ms is required. The short contraction is not treated as an activation.",
      "synthetic": true,
      "negative_example": true,
      "modality": ["voice_intent", "gaze", "emg"],
      "intended_target": "terminal",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated EMG band, simulated signal" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 830, "source": "activation", "event": "hold_start" },
        { "seq": 4, "t_ms": 910, "source": "gaze", "event": "sample" },
        { "seq": 5, "t_ms": 950, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.88, "age_ms": 90, "quality": "good" },
        "voice": { "intent": "copy", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "emg_hold",
          "confidence": 0.9,
          "age_ms": 50,
          "hold_ms": 120,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "copy", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "accidental_blink",
      "title": "Accidental double blink",
      "description": "Negative example. A second blink arrives 180 ms after the first, inside the 400 ms refractory window. A reflex blink pair is not a deliberate activation.",
      "synthetic": true,
      "negative_example": true,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated bright glare", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 780, "source": "activation", "event": "first_blink" },
        { "seq": 4, "t_ms": 890, "source": "gaze", "event": "sample" },
        { "seq": 5, "t_ms": 960, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.9, "age_ms": 110, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.85,
          "age_ms": 40,
          "hold_ms": 0,
          "bounce_count": 1,
          "bounce_gap_ms": 180,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "confirmation_required",
      "title": "Confirmation required",
      "description": "'Send' is destructive. Even with a clean gaze on Mail and a valid blink, the resolver asks for explicit confirmation.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "mail",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 50, "y": 78, "confidence": 0.9, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "send", "confidence": 0.92, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.9,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "ask_confirmation", "intent": "send", "target": "mail", "outcome": "awaiting_confirmation" }
    },
    {
      "id": "emergency_stop",
      "title": "Emergency stop",
      "description": "Every input would otherwise be valid, but the emergency stop is latched. Stop always wins over any other rule.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": null,
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" },
        { "seq": 5, "t_ms": 980, "source": "system", "event": "emergency_stop" }
      ],
      "inputs": {
        "emergency_stop": true,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.92, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "stop", "intent": "open", "target": null, "outcome": "stopped" }
    },
    {
      "id": "voice_only",
      "title": "Voice only",
      "description": "No gaze sensor is connected. Voice names Terminal explicitly and a valid EMG hold activates, so the named target is used.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "emg"],
      "intended_target": "terminal",
      "simulated_conditions": { "lighting": "not applicable (no camera path)", "device": "simulated EMG band, simulated signal" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 550, "source": "activation", "event": "hold_start" },
        { "seq": 3, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 4, "t_ms": 950, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": false, "x": 0, "y": 0, "confidence": null, "age_ms": 0, "quality": "unknown" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": "terminal" },
        "activation": {
          "kind": "emg_hold",
          "confidence": 0.9,
          "age_ms": 50,
          "hold_ms": 400,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "open", "target": "terminal", "outcome": "previewed" }
    },
    {
      "id": "gaze_plus_voice",
      "title": "Gaze plus voice agree",
      "description": "Gaze is on Terminal and the user also says 'copy terminal'. Both modalities name the same window, so the proposal is accepted.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "terminal",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.9, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "copy", "confidence": 0.88, "target_ref": "terminal" },
        "activation": {
          "kind": "blink",
          "confidence": 0.9,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "copy", "target": "terminal", "outcome": "previewed" }
    },
    {
      "id": "face_gesture_activation",
      "title": "Face gesture activation",
      "description": "A simulated raised-eyebrow gesture at 0.82 confidence activates the proposal for the gazed window, Notes.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated webcam landmark model" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 910, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 930, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.86, "age_ms": 90, "quality": "good" },
        "voice": { "intent": "copy", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "face_gesture",
          "confidence": 0.82,
          "age_ms": 70,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "copy", "target": "notes", "outcome": "previewed" }
    },
    {
      "id": "emg_switch_activation",
      "title": "EMG switch activation",
      "description": "A simulated 380 ms EMG hold at 0.92 confidence meets the 250 ms minimum and activates the proposal for Mail.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "emg"],
      "intended_target": "mail",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated EMG band, simulated signal" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 580, "source": "activation", "event": "hold_start" },
        { "seq": 3, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 4, "t_ms": 920, "source": "gaze", "event": "sample" },
        { "seq": 5, "t_ms": 960, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 50, "y": 78, "confidence": 0.88, "age_ms": 80, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "emg_hold",
          "confidence": 0.92,
          "age_ms": 40,
          "hold_ms": 380,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "open", "target": "mail", "outcome": "previewed" }
    },
    {
      "id": "eeg_eog_experimental",
      "title": "EEG/EOG experimental event",
      "description": "Experimental research proposal only. A simulated coarse EEG/EOG event at 0.95 confidence is valid, but experimental activation never auto-accepts, so confirmation is required.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "eeg_eog_experimental"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated EEG/EOG headband, simulated signal" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 920, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.9, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "eeg_eog",
          "confidence": 0.95,
          "age_ms": 80,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "ask_confirmation", "intent": "open", "target": "notes", "outcome": "awaiting_confirmation" }
    },
    {
      "id": "incorrect_target_selection",
      "title": "Incorrect target selection",
      "description": "The user means Notes but a simulated calibration drift puts a confident gaze on Terminal. 'Delete' is destructive, so the resolver asks for confirmation and names Terminal, which lets the user cancel. It is not counted as a wrong-target action because nothing was accepted.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, drifted calibration" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.8, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "delete", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "ask_confirmation", "intent": "delete", "target": "terminal", "outcome": "awaiting_confirmation" }
    },
    {
      "id": "sensor_disconnection",
      "title": "Sensor disconnection",
      "description": "The gaze sensor drops out mid-session and voice names no target. With no usable target source the resolver abstains and suggests the keyboard or a spoken target.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, link lost" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 400, "source": "gaze", "event": "disconnect" },
        { "seq": 3, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": false, "x": 0, "y": 0, "confidence": null, "age_ms": 0, "quality": "unknown" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "false_activation",
      "title": "False activation",
      "description": "Negative example. A simulated muscle twitch holds 300 ms, long enough, but at 0.55 confidence, below the 0.8 EMG floor. It is rejected as a false activation.",
      "synthetic": true,
      "negative_example": true,
      "modality": ["voice_intent", "gaze", "emg"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated EMG band, simulated motion noise" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 640, "source": "activation", "event": "hold_start" },
        { "seq": 3, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 4, "t_ms": 910, "source": "gaze", "event": "sample" },
        { "seq": 5, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.9, "age_ms": 90, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "emg_hold",
          "confidence": 0.55,
          "age_ms": 60,
          "hold_ms": 300,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "degraded"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "out_of_order_sample",
      "title": "Out-of-order sample",
      "description": "A gaze sample stamped 100 ms arrives after the activation stamped 940 ms. At the decision it is 900 ms old, past the 500 ms limit, so it is stale and the resolver abstains instead of trusting a late sample.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 940, "source": "activation", "event": "activation" },
        { "seq": 4, "t_ms": 100, "source": "gaze", "event": "sample", "out_of_order": true }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.9, "age_ms": 900, "quality": "degraded" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "emg_hold_chatter",
      "title": "EMG hold chatter",
      "description": "Negative example. The EMG signal chatters: a 120 ms contraction, then a second one 35 ms after the first ended. A hold must last at least 250 ms, so no activation is accepted.",
      "synthetic": true,
      "negative_example": true,
      "modality": ["voice_intent", "gaze", "emg"],
      "intended_target": "terminal",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated EMG band, simulated signal" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 800, "source": "activation", "event": "hold_start" },
        { "seq": 4, "t_ms": 905, "source": "gaze", "event": "sample" },
        { "seq": 5, "t_ms": 920, "source": "activation", "event": "hold_end" },
        { "seq": 6, "t_ms": 955, "source": "activation", "event": "hold_start" },
        { "seq": 7, "t_ms": 960, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 74, "y": 30, "confidence": 0.88, "age_ms": 95, "quality": "good" },
        "voice": { "intent": "copy", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "emg_hold",
          "confidence": 0.9,
          "age_ms": 40,
          "hold_ms": 120,
          "bounce_count": 2,
          "bounce_gap_ms": 35,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "copy", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "ambiguous_gaze_edge",
      "title": "Ambiguous gaze target",
      "description": "Gaze rests on Notes, 4.5% from the edge of Terminal, with high confidence; the intent names no target. The point could belong to either window, so the resolver abstains and asks for a spoken target.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 47.5, "y": 30, "confidence": 0.92, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "open", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "untrusted_target",
      "title": "Untrusted target window",
      "description": "Gaze and voice agree on the Browser window, which the simulated desktop marks as an unverified page. A trusted action is never proposed on an untrusted window, so the resolver abstains.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "browser",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 3, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 4, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 82, "y": 78, "confidence": 0.9, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "copy", "confidence": 0.88, "target_ref": "browser" },
        "activation": {
          "kind": "blink",
          "confidence": 0.9,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "abstain", "intent": "copy", "target": null, "outcome": "nothing_proposed" }
    },
    {
      "id": "sensor_recovery",
      "title": "Sensor recovery",
      "description": "The gaze sensor drops out at 100 ms and reconnects at 500 ms. By the decision it delivers fresh samples again, and the normal gaze-plus-blink proposal is made on Notes.",
      "synthetic": true,
      "negative_example": false,
      "modality": ["voice_intent", "gaze", "face"],
      "intended_target": "notes",
      "simulated_conditions": { "lighting": "simulated even office light", "device": "simulated eye tracker, 60 Hz class" },
      "decision_at_ms": 1000,
      "timeline": [
        { "seq": 1, "t_ms": 0, "source": "system", "event": "scenario_start" },
        { "seq": 2, "t_ms": 100, "source": "gaze", "event": "disconnect" },
        { "seq": 3, "t_ms": 500, "source": "gaze", "event": "reconnect" },
        { "seq": 4, "t_ms": 700, "source": "voice", "event": "utterance" },
        { "seq": 5, "t_ms": 900, "source": "gaze", "event": "sample" },
        { "seq": 6, "t_ms": 940, "source": "activation", "event": "activation" }
      ],
      "inputs": {
        "emergency_stop": false,
        "gaze": { "connected": true, "x": 25, "y": 30, "confidence": 0.85, "age_ms": 100, "quality": "good" },
        "voice": { "intent": "open", "confidence": 0.9, "target_ref": null },
        "activation": {
          "kind": "blink",
          "confidence": 0.88,
          "age_ms": 60,
          "hold_ms": 0,
          "bounce_count": 0,
          "bounce_gap_ms": null,
          "quality": "good"
        }
      },
      "expected": { "decision": "accept", "intent": "open", "target": "notes", "outcome": "previewed" }
    }
  ],
  "consent": { "required": false, "reason": "Synthetic data only; no person was recorded, so no consent is needed." }
};
