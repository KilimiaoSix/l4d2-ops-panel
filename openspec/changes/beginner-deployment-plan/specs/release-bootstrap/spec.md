## ADDED Requirements

### Requirement: R1 Complete versioned release
The release SHALL contain a built SPA, fixed runtime dependency constraints, normalized plugin payloads, one canonical pack manifest, version information and upstream provenance/license materials; it MUST exclude deployment secrets and mutable user data.

#### Scenario: Install from the final archive
- **WHEN** a clean host consumes a release archive
- **THEN** the panel runtime finds the actual bundled payloads using `panel/packs/manifest.json`
- **AND** no Node or SourceMod compiler is required on that host.

#### Scenario: Unresolved upstream dependency
- **WHEN** a selected full-pack dependency has no pinned source, checksum, compatible binary or redistribution materials
- **THEN** release validation fails rather than publishing an incomplete full pack, except for the explicitly approved L4DToolZ official-download dependency, whose exact version, URL, hash and file mapping MUST be pinned and verified before installation commits.

### Requirement: R2 Verified GitHub distribution and optional mirror fallback
The bootstrap SHALL obtain the versioned script and release assets from this repository's GitHub Releases, with explicit initial-script trust and an authenticated release checksum manifest. A separately hosted mirror SHALL be optional; neither building nor publishing a candidate MUST require the game server to host release assets.

#### Scenario: GitHub-only release
- **WHEN** the release configuration has no mirror
- **THEN** the release workflow can render, sign and verify a candidate whose installer downloads from the fixed GitHub Releases version
- **AND** GitHub download failure reports retry, optional HTTPS mirror or signed offline installation guidance without disabling verification.

#### Scenario: Primary download unavailable
- **WHEN** GitHub is unavailable and a configured mirror is available
- **THEN** the explicitly configured mirror can supply the same signed versioned script and release assets
- **AND** release verification succeeds before installation changes are committed.

#### Scenario: Mirror content modified
- **WHEN** a mirror substitutes the archive or its checksum manifest without the release signing authority
- **THEN** installation fails without replacing the existing installation.

### Requirement: R3 Supported zero-question bootstrap
The bootstrap SHALL support root execution on Ubuntu 22.04/24.04 x86_64 with systemd, create a dedicated service identity, and install the required environment without interactive technical questions.

#### Scenario: Clean supported machine
- **WHEN** the user runs the documented installation command
- **THEN** Python/venv, Docker/Compose, HTTPS and systemd are configured and the service runs under the dedicated identity
- **AND** the game directory remains absent or empty for subsequent game installation.

#### Scenario: Unsupported or failed environment
- **WHEN** architecture/systemd is unsupported, a foreign installation conflicts, or Docker installation fails
- **THEN** the script exits nonzero with a concrete diagnosis and retry/recovery command
- **AND** it does not claim the server is ready to play or delete unrelated services.

### Requirement: R4 Safe initial owner creation
The new bootstrap SHALL seed an owner with a random initial password before exposing first-use access; existing accounts MUST remain unchanged and the legacy setup operation MUST be atomic.

#### Scenario: Fresh bootstrap
- **WHEN** the new panel becomes reachable
- **THEN** an owner already exists and only the installation terminal receives the initial credential
- **AND** ordinary API responses and audit/job logs do not reveal it.

#### Scenario: Concurrent legacy initialization
- **WHEN** two valid first-owner setup requests run against an empty legacy database
- **THEN** exactly one succeeds, the other receives 409, and only one owner is created.

### Requirement: R5 Idempotent update and recovery
Explicit bootstrap reruns SHALL preserve deployment data, verify ownership, and confirm a new running version when changing releases; failure MUST retain or restore a usable prior installation.

#### Scenario: Update an existing managed installation
- **WHEN** a user explicitly reruns for a newer release
- **THEN** the old panel is stopped before replacement, configuration/DB/certificates/game/receipts are preserved, and the new process version is checked.

#### Scenario: Failed replacement
- **WHEN** the replacement fails validation or startup
- **THEN** old code and applicable configuration are restored with a clear result
- **AND** existing accounts and game data are not reset.

### Requirement: R6 Concrete network and recovery guidance
The bootstrap SHALL report the correct panel URL, certificate guidance, host/cloud port requirements and bounded repair commands without asserting unverified public connectivity.

#### Scenario: Default or custom game port
- **WHEN** the user installs or selects a different game port
- **THEN** the UI/terminal identifies that port's TCP and UDP requirements and supplies a restricted host-rule repair command when needed
- **AND** cloud security-group changes remain explicitly user-managed.

#### Scenario: Panel unreachable after configuration
- **WHEN** automatic recovery cannot restore access
- **THEN** the documented single recovery command restores a validated previous panel configuration without deleting accounts or game data.
