## ADDED Requirements

### Requirement: B1 Persistent verified Chinese name
The panel SHALL store valid UTF-8 server names outside engine CFG, support a safe ASCII fallback and verify the actual applied name through the bundled hostname plugin across map changes and restarts.

#### Scenario: Valid or oversized UTF-8 name
- **WHEN** the user submits a safe 1–96 byte UTF-8 name
- **THEN** its normalized bytes are persisted and can be compared exactly with plugin-reported runtime bytes
- **AND** a name over 96 bytes or containing prohibited controls is rejected before any write.

#### Scenario: Map change or competing name plugin
- **WHEN** server.cfg or another plugin changes hostname after map start
- **THEN** the hostname plugin uses bounded, non-reentrant correction and reports divergence if it cannot maintain the configured name
- **AND** the UI never labels a mismatched name verified.

### Requirement: B2 Safe password and region persistence
The panel SHALL support setting/clearing join passwords and region without damaging unrelated CFG or revealing passwords in read responses/audits.

#### Scenario: Clear then set password
- **WHEN** the user saves an empty password and later saves a new one
- **THEN** `sv_password ""` remains parseable, the empty state persists, and the later save succeeds
- **AND** omitting the password field leaves the existing password unchanged.

#### Scenario: Runtime password is protected
- **WHEN** the engine refuses or masks password readback
- **THEN** the UI reports saved but runtime-unverified instead of equating the mask with the requested password.

#### Scenario: Region outside supported values
- **WHEN** region is outside 0–7 and 255
- **THEN** validation rejects it before changing files or runtime values.

### Requirement: B3 Playable optional multiplayer count
With the verified multiplayer package installed, the panel SHALL support 4–12 cooperative players by configuring engine capacity, human-player limits, survivor generation and relevant lobby rules separately within a validated capacity budget.

#### Scenario: Request more than four players
- **WHEN** the user saves eight or twelve cooperative players with the required capabilities active
- **THEN** all necessary profile values are persisted, required restarts are explained, and actual extra survivors can join
- **AND** sv_setmax is not treated as equivalent to the requested human-player count.

#### Scenario: Invalid count or missing dependencies
- **WHEN** the request is non-integer, below 4, above 12, conflicts with the infected/client budget or lacks the required stack
- **THEN** the update is rejected with the specific reason and an appropriate package-install path
- **AND** no partially valid player count is reported as applied.

### Requirement: B4 Honest transactional save and apply
Basic settings SHALL share CFG synchronization with existing mode/damage changes, use revisions and recoverable multi-file saves, and separate saved, applied, unverified, error and restart-required results.

#### Scenario: Saving fails or revision changed
- **WHEN** any required file cannot be saved or a concurrent writer invalidates the revision
- **THEN** the operation preserves/restores its version-matched prior files, reports the failure and sends no game-changing RCON command.

#### Scenario: Partial runtime application
- **WHEN** files save but one runtime operation fails, is adjusted or requires restart
- **THEN** each field reports its actual outcome without claiming all settings are active
- **AND** a stale cached capability result alone does not suppress a fresh explicit runtime check.
