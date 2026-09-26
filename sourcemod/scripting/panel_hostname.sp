// SPDX-License-Identifier: MIT
#include <sourcemod>
#pragma newdecls required
#pragma semicolon 1

public Plugin myinfo = {
    name = "Panel Hostname", author = "l4d2-ops-panel",
    description = "UTF-8 hostname file and exact ASCII receipt", version = "1.0.0", url = ""
};

ConVar g_Hostname;
char g_Path[PLATFORM_MAX_PATH];
char g_Wanted[97];
char g_State[16] = "missing";
bool g_Applying;
int g_Corrections;

public void OnPluginStart()
{
    g_Hostname = FindConVar("hostname");
    if (g_Hostname == null) SetFailState("hostname convar is missing");
    BuildPath(Path_SM, g_Path, sizeof(g_Path), "data/panel_hostname.txt");
    g_Hostname.AddChangeHook(OnHostnameChanged);
    RegAdminCmd("sm_panel_hostname_reload", ReloadHostname, ADMFLAG_ROOT, "Load hostname and report byte receipt");
    RegAdminCmd("sm_panel_hostname_status", HostnameStatus, ADMFLAG_ROOT, "Report expected and actual UTF-8 bytes as hex");
    LoadHostname();
}

public void OnMapStart() { LoadHostname(); }

void LoadHostname()
{
    g_Corrections = 0;
    g_Wanted[0] = '\0';
    File file = OpenFile(g_Path, "r");
    if (file == null) { strcopy(g_State, sizeof(g_State), "missing"); return; }
    char line[100], extra[2];
    bool read = file.ReadLine(line, sizeof(line));
    bool more = file.ReadLine(extra, sizeof(extra));
    delete file;
    int length = strlen(line);
    if (length > 0 && line[length - 1] == '\n') line[--length] = '\0';
    if (length > 0 && line[length - 1] == '\r') line[--length] = '\0';
    if (!read || more || length < 1 || length > 96) { strcopy(g_State, sizeof(g_State), "invalid"); return; }
    for (int i = 0; i < length; i++) {
        int b = line[i] & 255;
        if (b < 32 || b == 127 || b == 34 || b == 59 || b == 92) {
            strcopy(g_State, sizeof(g_State), "invalid"); return;
        }
    }
    strcopy(g_Wanted, sizeof(g_Wanted), line);
    ApplyHostname();
}

void ApplyHostname()
{
    if (g_Applying || g_Wanted[0] == '\0') return;
    if (g_Corrections >= 8) { strcopy(g_State, sizeof(g_State), "limit"); return; }
    g_Corrections++;
    g_Applying = true;
    g_Hostname.SetString(g_Wanted);
    g_Applying = false;
    strcopy(g_State, sizeof(g_State), "loaded");
}

public void OnHostnameChanged(ConVar cv, const char[] oldValue, const char[] newValue)
{
    if (!g_Applying && g_Wanted[0] != '\0' && !StrEqual(newValue, g_Wanted)) ApplyHostname();
}

void Hex(const char[] input, char[] output, int size)
{
    static const char digits[] = "0123456789abcdef";
    int n = strlen(input), offset;
    for (int i = 0; i < n && offset + 2 < size; i++) {
        int value = input[i] & 255;
        output[offset++] = digits[value >> 4]; output[offset++] = digits[value & 15];
    }
    output[offset] = '\0';
}

void Receipt(int client)
{
    char actual[256], expectedHex[193], actualHex[511], state[16];
    g_Hostname.GetString(actual, sizeof(actual));
    Hex(g_Wanted, expectedHex, sizeof(expectedHex)); Hex(actual, actualHex, sizeof(actualHex));
    strcopy(state, sizeof(state), g_State);
    if (g_Wanted[0] != '\0' && !StrEqual(g_State, "limit"))
        strcopy(state, sizeof(state), StrEqual(actual, g_Wanted) ? "ok" : "mismatch");
    ReplyToCommand(client, "PANEL_HOSTNAME expected=%s actual=%s state=%s", expectedHex, actualHex, state);
}

public Action ReloadHostname(int client, int args) { LoadHostname(); Receipt(client); return Plugin_Handled; }
public Action HostnameStatus(int client, int args) { Receipt(client); return Plugin_Handled; }
