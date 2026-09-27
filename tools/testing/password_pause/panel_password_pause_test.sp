// SPDX-License-Identifier: GPL-3.0-or-later
#include <sourcemod>
#pragma newdecls required
#pragma semicolon 1

native int PanelPasswordTestPause(bool paused);

public Plugin myinfo = {
    name = "Panel Password Pause Test", author = "l4d2-ops-panel",
    description = "Temporary isolated-fixture lifecycle probe", version = "1.0.0", url = ""
};

public void OnPluginStart()
{
    RegServerCmd("sm_panel_password_pause_test", RunProbe);
}

public Action RunProbe(int args)
{
    ConVar password = FindConVar("sm_panel_join_password");
    ConVar nativePassword = FindConVar("sv_password");
    if (password == null || nativePassword == null) return Plugin_Handled;
    char expected[256], protectedValue[256], after[256];
    password.GetString(expected, sizeof(expected));
    if (!expected[0]) {
        PrintToServer("PANEL_PAUSE_TEST error=password_required");
        return Plugin_Handled;
    }
    int paused = PanelPasswordTestPause(true);
    nativePassword.GetString(protectedValue, sizeof(protectedValue));
    int resumed = PanelPasswordTestPause(false);
    nativePassword.GetString(after, sizeof(after));
    bool nativeClear = !after[0];
    password.GetString(after, sizeof(after));
    PrintToServer("PANEL_PAUSE_TEST paused=%d protected=%d running=%d native_clear=%d secret_preserved=%d",
        paused == 1, StrEqual(expected, protectedValue), resumed == 0, nativeClear, StrEqual(expected, after));
    return Plugin_Handled;
}
