#include <sourcemod>
#pragma newdecls required
#pragma semicolon 1

// Special-infected intensity presets: auto (scale by alive survivors) / te8 / te12 / te16.
// Switches the Infected Bots data file (l4d_infectedbots_read_data) and the common-infected cvars,
// remembers the choice in data/sipreset.txt and re-applies it every map.

public Plugin myinfo = { name = "SI Preset", author = "local", description = "!preset auto|te8|te12|te16", version = "1.0", url = "" };

char g_sPreset[16] = "auto";
char g_sPath[PLATFORM_MAX_PATH];

public void OnPluginStart()
{
	BuildPath(Path_SM, g_sPath, sizeof(g_sPath), "data/sipreset.txt");
	RegAdminCmd("sm_preset", Cmd_Preset, ADMFLAG_ROOT, "sm_preset [auto|te8|te12|te16]");
	RegConsoleCmd("sm_presetinfo", Cmd_Info, "Show current SI preset");
	File f = OpenFile(g_sPath, "r");
	if (f != null) { f.ReadLine(g_sPreset, sizeof(g_sPreset)); TrimString(g_sPreset); delete f; }
	if (!Valid(g_sPreset)) strcopy(g_sPreset, sizeof(g_sPreset), "auto");
}

bool Valid(const char[] p) { return StrEqual(p, "auto") || StrEqual(p, "te8") || StrEqual(p, "te12") || StrEqual(p, "te16"); }

// OnConfigsExecuted never fires on L4D2 (no servercfgfile cvar) and timers stall while hibernating -> use OnMapStart
public void OnMapStart() { Apply(false); }

void Apply(bool announce)
{
	int commons = 30, mobmin = 10, mobmax = 30, mega = 50;
	if (StrEqual(g_sPreset, "te12")) { commons = 25; mobmax = 20; mega = 40; }
	else if (StrEqual(g_sPreset, "te16")) { commons = 20; mobmax = 15; mega = 35; }
	else if (StrEqual(g_sPreset, "auto")) { commons = 25; mobmax = 20; mega = 40; }
	ServerCommand("sm_cvar l4d_infectedbots_read_data \"%s\"", StrEqual(g_sPreset, "auto") ? "" : g_sPreset);
	ServerCommand("sm_cvar z_common_limit %d", commons);
	ServerCommand("sm_cvar z_mob_spawn_min_size %d", mobmin);
	ServerCommand("sm_cvar z_mob_spawn_max_size %d", mobmax);
	ServerCommand("sm_cvar z_mega_mob_size %d", mega);
	if (announce) PrintToChatAll("[预设] 特感强度: %s (普通僵尸上限 %d)", g_sPreset, commons);
	LogMessage("sipreset applied: %s (commons %d)", g_sPreset, commons);
}

public Action Cmd_Preset(int client, int args)
{
	if (args < 1)
	{
		ReplyToCommand(client, "[预设] 当前: %s | 可选: auto(按人数 4-16) te8 te12 te16", g_sPreset);
		return Plugin_Handled;
	}
	char p[16]; GetCmdArg(1, p, sizeof(p)); TrimString(p);
	if (!Valid(p)) { ReplyToCommand(client, "[预设] 无效，可选: auto te8 te12 te16"); return Plugin_Handled; }
	strcopy(g_sPreset, sizeof(g_sPreset), p);
	File f = OpenFile(g_sPath, "w");
	if (f != null) { f.WriteLine("%s", g_sPreset); delete f; }
	Apply(true);
	return Plugin_Handled;
}

public Action Cmd_Info(int client, int args)
{
	ReplyToCommand(client, "[预设] 当前特感强度: %s", g_sPreset);
	return Plugin_Handled;
}
