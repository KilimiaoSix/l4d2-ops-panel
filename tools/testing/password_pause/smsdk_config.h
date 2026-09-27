// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#define SMEXT_CONF_NAME "Panel Password Pause Test"
#define SMEXT_CONF_DESCRIPTION "Isolated-fixture password lifecycle probe"
#define SMEXT_CONF_VERSION "1.0.0"
#define SMEXT_CONF_AUTHOR "l4d2-ops-panel"
#define SMEXT_CONF_URL ""
#define SMEXT_CONF_LOGTAG "PANEL_PAUSE_TEST"
#define SMEXT_CONF_LICENSE "GPL-3.0-or-later"
#define SMEXT_CONF_DATESTRING __DATE__
#define SMEXT_LINK(name) SDKExtension *g_pExtensionIface = name;
#define SMEXT_ENABLE_PLUGINSYS
