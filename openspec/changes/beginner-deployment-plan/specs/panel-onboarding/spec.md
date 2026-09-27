## ADDED Requirements

### Requirement: O1 Persistent onboarding lifecycle
The panel SHALL persist onboarding completion and progress independently of account existence and SHALL integrate environment, game, plugin, basic settings and join steps.

#### Scenario: Restart during first setup
- **WHEN** an owner exists and the panel restarts before the wizard is complete
- **THEN** the wizard resumes with the unfinished steps instead of being dismissed.

#### Scenario: Upgrade an existing panel
- **WHEN** a previously used panel first receives the onboarding schema
- **THEN** migration runs once without forcing first-install steps
- **AND** the owner can explicitly reopen onboarding later.

#### Scenario: Submit completion
- **WHEN** the owner completes onboarding
- **THEN** server-side checks verify the required installation and saved settings
- **AND** unverified public access is labeled as unverified rather than certified ready.

### Requirement: O2 Usable state before game installation
Game-dependent pages SHALL provide an actionable empty state and preserve an empty game target before installation; reads MUST NOT create game files.

#### Scenario: Navigate every page on a clean install
- **WHEN** game_dir does not yet exist and the owner visits all nine existing views
- **THEN** each page shows valid empty data or a meaningful unavailable state with an installation link
- **AND** no unhandled missing-directory error or game-directory creation occurs.

#### Scenario: Enter wizard settings early
- **WHEN** the user enters a name or other options while game installation is unfinished
- **THEN** only non-secret onboarding draft data may persist outside game_dir
- **AND** game configuration is written only after successful game installation.

### Requirement: O3 Actionable friend connection guide
The panel SHALL provide a validated join address, a copy action, developer-console instructions and client-content/password guidance without leaking secrets.

#### Scenario: Share server information
- **WHEN** the user copies the join instructions
- **THEN** the address contains the selected game port exactly once and explains how to use the L4D2 console
- **AND** the shared text contains no panel, RCON, Steam API or automatically included join password.

### Requirement: O4 Honest connectivity evidence
The panel SHALL distinguish installation, engine availability and external-player connectivity, including host and cloud TCP/UDP requirements.

#### Scenario: Local checks succeed but public access fails
- **WHEN** Docker runs and local RCON/A2S responds but a friend cannot join
- **THEN** the UI retains the separate unverified-public state and presents relevant network/address checks
- **AND** it does not treat a successful TCP probe as proof of UDP reachability.
