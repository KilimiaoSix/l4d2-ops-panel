## ADDED Requirements

### Requirement: C1 Authorized exact configuration target
Only owners SHALL edit explicitly writable panel configuration, targeting the file selected by the actual startup configuration path; secrets MUST be write-only in this API.

#### Scenario: External configuration file
- **WHEN** the process uses --config or L4D2PANEL_CONFIG outside panel base
- **THEN** read, revision, backup, write and restart all use that exact file.

#### Scenario: Unknown key or insufficient role
- **WHEN** an update contains an unknown/non-writable key or comes from an admin instead of owner
- **THEN** it is rejected before changing disk or runtime state
- **AND** the error does not contain secret values.

### Requirement: C2 Versioned atomic saves
Configuration updates SHALL validate the entire candidate before writing, preserve existing unrelated fields, use optimistic revisions and secure backups, and avoid writes for unchanged values.

#### Scenario: Stale editor
- **WHEN** another writer changed the configuration after it was loaded
- **THEN** the update returns 409 without overwriting the newer contents.

#### Scenario: Invalid candidate or write failure
- **WHEN** a candidate has invalid types/ports/TLS files or atomic save fails
- **THEN** the prior usable configuration and running settings remain intact.

### Requirement: C3 Correct effect classification
The panel SHALL apply supported live fields to all consumers and require explicit restart confirmation for restart fields, with installation-bound paths locked after installation.

#### Scenario: Change Steam API key live
- **WHEN** an owner updates steam_api_key
- **THEN** both workshop features and the existing SteamClient vanity-resolution path observe the new value without restart.

#### Scenario: Unconfirmed restart or forbidden relocation
- **WHEN** restart fields are submitted without restart confirmation or a managed installed game is relocated through settings
- **THEN** the update returns a conflict and does not save partial changes.

### Requirement: C4 Exclusive supervised restart
Restart SHALL be available only with a verified supported supervisor and SHALL atomically exclude running/new background jobs and conflicting game/file operations.

#### Scenario: Job races restart
- **WHEN** a job starts concurrently with a restart request
- **THEN** one operation is accepted and the other is rejected as busy
- **AND** no accepted job is killed by the configuration restart.

#### Scenario: No supervisor
- **WHEN** the panel runs standalone
- **THEN** restart-effect updates are unavailable and the panel does not exit itself.

### Requirement: C5 Verified restart and bounded recovery
The restart flow SHALL confirm a new process/configuration, handle listener changes and provide bounded version-safe rollback plus a single-command recovery path.

#### Scenario: Same port or new origin
- **WHEN** configuration keeps the listener port or changes port/TLS/bind
- **THEN** preflight does not collide with the panel's own listener
- **AND** the UI uses boot/config evidence for same-origin recovery or an explicit new-address navigation and login explanation for a new origin.

#### Scenario: Candidate startup fails
- **WHEN** a pending candidate cannot start
- **THEN** the prior configuration is restored at most once if no external edit conflicts
- **AND** unresolved failure gives a usable recovery command rather than an infinite restart loop.
