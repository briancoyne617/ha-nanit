# Nanit HA Integration
# Show available commands
default:
    @just --list

# Login to Nanit cloud (saves session to .nanit-session)
login *args:
    python3 tools/nanit-login.py {{args}}

# Fetch activity events from Nanit cloud API (default: 10)
# Examples: just events    |    just events --limit 5
events *args:
    python3 tools/nanit-events.py {{args}}

# Dump raw /babies API response — shows all device UIDs (camera, sound machine, etc.)
devices:
    python3 tools/nanit-devices.py

# Probe Nanit Sound + Light machine (requires active session from: just login)
# Uses wss://remote.nanit.com/speakers/{uid}/user_connect/ with speaker proto.
# Examples:
#   just probe-audio state                    # current state
#   just probe-audio sounds                   # list tracks
#   just probe-audio stop                     # turn off
#   just probe-audio play                     # turn on
#   just probe-audio set-sound "Brown Noise"  # set track by name
#   just probe-audio set-volume 50            # set volume 0-100
probe-audio *args:
    python3 tools/probe_audio.py {{args}}

# Create a GitHub release by bumping the latest version.
# Usage: just release <patch|minor|major>
# Example: just release patch  (0.2.1 → 0.2.2)
release bump:
    #!/usr/bin/env bash
    set -euo pipefail
    # Get latest version tag, strip 'v' prefix
    latest=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
    latest="${latest#v}"
    IFS='.' read -r major minor patch <<< "${latest}"
    case "{{bump}}" in
        patch) patch=$((patch + 1)) ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        major) major=$((major + 1)); minor=0; patch=0 ;;
        *) echo "Error: Invalid bump type '{{bump}}'. Use patch, minor, or major."; exit 1 ;;
    esac
    new="${major}.${minor}.${patch}"
    tag="v${new}"
    echo "Bumping: ${latest} → ${new}"
    # Update manifest.json
    sed -i '' 's/"version": "[0-9]*\.[0-9]*\.[0-9]*"/"version": "'"${new}"'"/' custom_components/nanit/manifest.json
    # Update aionanit pyproject.toml
    sed -i '' 's/^version = "[0-9]*\.[0-9]*\.[0-9]*"/version = "'"${new}"'"/' packages/aionanit/pyproject.toml
    git add custom_components/nanit/manifest.json packages/aionanit/pyproject.toml
    git commit -m "Bump version to ${new}"
    git tag "${tag}"
    git push && git push --tags
    gh release create "${tag}" --title "${tag}" --generate-notes
    echo "Released ${tag}"
