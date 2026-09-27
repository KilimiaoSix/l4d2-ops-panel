## ADDED Requirements

### Requirement: P1 Minimal and full dependency profiles
The panel SHALL default to the agreed minimal profile and allow full/individual compatible packages both during setup and afterward, resolving real pinned dependencies from the canonical release manifest.

#### Scenario: Minimal installation
- **WHEN** the user accepts the default selection
- **THEN** only the base framework, bundled whitelist/preset helper and hostname support are installed
- **AND** preset capability remains unavailable with an explanatory expansion path until its required Infected Bots stack exists.

#### Scenario: Optional full installation
- **WHEN** the user selects the full profile initially or after a minimal install
- **THEN** the server resolves and installs the compatible multiplayer, infected and points dependency closure
- **AND** unknown package IDs, dependency cycles and incompatible combinations fail validation.

#### Scenario: Approved official L4DToolZ download
- **WHEN** the selected dependency closure includes L4DToolZ
- **THEN** the installer downloads only its pinned official release, verifies its SHA256 and safely stages the declared files before modifying the game
- **AND** failed downloads, unsafe archives or incorrect hashes leave the game unchanged and allow retry.

### Requirement: P2 Safe package file ownership
Installation SHALL validate all source and destination paths and preserve user configuration, administrator files, data and unowned installations.

#### Scenario: Existing custom data
- **WHEN** package files overlap existing hostname, whitelist, admins, IB data or plugin configuration
- **THEN** user data is retained and new defaults initialize missing files only.

#### Scenario: Unsafe or foreign target
- **WHEN** a source/target escapes the allowed roots, uses unsafe links/types, contains engine-unsafe CFG, or conflicts with unowned framework files
- **THEN** the package is rejected without overwriting that target.

### Requirement: P3 Recoverable installation transaction
Package commits SHALL occur with the game stopped and a shared operation lock, using staged validation, persistent versioned transaction records and recoverable cancellation/failure handling.

#### Scenario: User permits stop and install
- **WHEN** a game is running and the user confirms stop_game
- **THEN** the controlled runtime stops before any package files are committed
- **AND** a failure to stop causes no package mutation.

#### Scenario: Interrupted file commit
- **WHEN** cancellation, I/O failure or process interruption occurs mid-commit
- **THEN** the system restores its unchanged transaction-owned files or reports an explicit incomplete recoverable transaction
- **AND** it does not publish a complete installed receipt or automatically start a partially installed game.

### Requirement: P4 Verified package capability status
The panel SHALL distinguish installed files, pending restart, active dependencies and unknown probe results; progress SHALL use consistent units and reads MUST NOT mutate installation state.

#### Scenario: Restart after installing SourceMod
- **WHEN** the user starts or restarts the game after a successful package transaction
- **THEN** relevant caches are invalidated and runtime checks establish active capabilities
- **AND** transient probe failures remain unknown instead of cached definite absence.

#### Scenario: Inspect interrupted installation
- **WHEN** a user reads package status
- **THEN** durable receipts/journals explain the state without a GET silently deleting staging files
- **AND** task progress uses file counts consistently for done and total.
