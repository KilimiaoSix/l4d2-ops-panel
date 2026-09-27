// SPDX-License-Identifier: MIT
#include <sourcemod>
#pragma newdecls required
#pragma semicolon 1

public Plugin myinfo = {
    name = "Panel Join Password", author = "l4d2-ops-panel",
    description = "L4D2 join password without the broken native dialog", version = "1.0.0", url = ""
};

ConVar g_Password, g_Native;
char g_Wanted[65];
bool g_Ready, g_Updating;

public void OnPluginStart()
{
    g_Native = FindConVar("sv_password");
    if (g_Native == null) SetFailState("sv_password convar is missing");
    g_Password = CreateConVar("sm_panel_join_password", "", "Join password; clients use setinfo l4d2_password", FCVAR_PROTECTED | FCVAR_DONTRECORD);
    g_Password.AddChangeHook(PasswordChanged);
    g_Native.AddChangeHook(NativePasswordChanged);
    RegAdminCmd("sm_panel_password_status", PasswordStatus, ADMFLAG_ROOT, "Report password enforcement without the secret");
    // Hibernation can defer OnConfigsExecuted until a player joins. Initialize
    // from current convars now; hooks apply every later password assignment.
    OnConfigsExecuted();
}

public void OnConfigsExecuted()
{
    char legacy[256];
    g_Native.GetString(legacy, sizeof(legacy));
    if (legacy[0]) {
        g_Updating = true;
        g_Password.SetString(legacy);
        g_Updating = false;
    }
    ApplyPassword();
}

void ProtectNative()
{
    FindConVar("sv_allow_lobby_connect_only").SetInt(0);
    char password[256];
    g_Password.GetString(password, sizeof(password));
    g_Updating = true;
    if (password[0]) g_Native.SetString(password);
    g_Updating = false;
}

void ApplyPassword()
{
    char value[256];
    g_Password.GetString(value, sizeof(value));
    g_Ready = strlen(value) <= 64;
    for (int i = 0; value[i]; i++) {
        if (value[i] < 32 || value[i] > 126 || value[i] == '"' || value[i] == ';' || value[i] == '\\') g_Ready = false;
    }
    if (!g_Ready) { ProtectNative(); return; }
    strcopy(g_Wanted, sizeof(g_Wanted), value);
    g_Updating = true;
    g_Native.SetString("");
    g_Updating = false;
}

public void NativePasswordChanged(ConVar cv, const char[] oldValue, const char[] newValue)
{
    if (g_Updating) return;
    g_Updating = true;
    g_Password.SetString(newValue);
    g_Updating = false;
    ApplyPassword();
}

public void PasswordChanged(ConVar cv, const char[] oldValue, const char[] newValue)
{
    if (!g_Updating) ApplyPassword();
}

public bool OnClientConnect(int client, char[] rejectmsg, int maxlen)
{
    if (IsFakeClient(client)) return true;
    if (!g_Ready) {
        strcopy(rejectmsg, maxlen, "Server password validation is not ready. Please retry later.");
        return false;
    }
    if (!g_Wanted[0]) return true;
    char supplied[256];
    if (GetClientInfo(client, "l4d2_password", supplied, sizeof(supplied)) && StrEqual(supplied, g_Wanted)) return true;
    strcopy(rejectmsg, maxlen, "Wrong join password. Use: setinfo l4d2_password YOUR_PASSWORD; connect SERVER_IP:PORT");
    return false;
}

public void OnPluginEnd()
{
    if (g_Native != null && (!g_Ready || g_Wanted[0])) ProtectNative();
}

public void OnPluginPauseChange(bool pause)
{
    if (pause) { if (!g_Ready || g_Wanted[0]) ProtectNative(); }
    else ApplyPassword();
}

public Action PasswordStatus(int client, int args)
{
    ReplyToCommand(client, "PANEL_PASSWORD ready=%d required=%d", g_Ready, g_Wanted[0] != '\0');
    return Plugin_Handled;
}
