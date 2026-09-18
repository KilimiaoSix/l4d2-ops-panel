#include <sourcemod>
#pragma newdecls required
#pragma semicolon 1

// Private server without a password: only SteamIDs listed in
// addons/sourcemod/configs/whitelist.txt (or SourceMod admins) may stay connected.
// An empty/missing whitelist.txt means "open to everyone" (so you cannot lock yourself out by accident).

public Plugin myinfo =
{
	name = "Private Whitelist",
	author = "local",
	description = "Kick players whose SteamID is not in configs/whitelist.txt (admins always pass)",
	version = "1.0",
	url = ""
};

ConVar g_cvEnable;
StringMap g_Allowed;
char g_sPath[PLATFORM_MAX_PATH];
char g_sStatePath[PLATFORM_MAX_PATH];   // remembers the on/off switch across restarts

public void OnPluginStart()
{
	g_cvEnable = CreateConVar("sm_whitelist_enable", "1", "1 = only whitelisted SteamIDs / admins may join, 0 = open", _, true, 0.0, true, 1.0);
	BuildPath(Path_SM, g_sPath, sizeof(g_sPath), "configs/whitelist.txt");
	g_Allowed = new StringMap();
	BuildPath(Path_SM, g_sStatePath, sizeof(g_sStatePath), "data/whitelist_enabled.txt");
	File sf = OpenFile(g_sStatePath, "r");
	if (sf != null) { char v[8]; sf.ReadLine(v, sizeof(v)); TrimString(v); g_cvEnable.SetInt(StringToInt(v)); delete sf; }
	g_cvEnable.AddChangeHook(OnEnableChanged);
	RegAdminCmd("sm_wl_add",    Cmd_Add,    ADMFLAG_BAN, "sm_wl_add <#userid|name> - add an online player to the whitelist");
	RegAdminCmd("sm_wl_addid",  Cmd_AddId,  ADMFLAG_BAN, "sm_wl_addid <STEAM_1:x:y> [note] - add a SteamID");
	RegAdminCmd("sm_wl_del",    Cmd_Del,    ADMFLAG_BAN, "sm_wl_del <STEAM_1:x:y> - remove a SteamID");
	RegAdminCmd("sm_wl_list",   Cmd_List,   ADMFLAG_BAN, "sm_wl_list - show the whitelist");
	RegAdminCmd("sm_wl_reload", Cmd_Reload, ADMFLAG_BAN, "sm_wl_reload - reload whitelist.txt");
	LoadList();
}

public void OnMapStart() { LoadList(); }

public void OnEnableChanged(ConVar cv, const char[] o, const char[] n)
{
	File f = OpenFile(g_sStatePath, "w");
	if (f != null) { f.WriteLine("%d", cv.IntValue); delete f; }
	LogMessage("whitelist %s", cv.BoolValue ? "ENABLED" : "DISABLED (open to everyone)");
}

void NormalizeId(char[] id, int maxlen)
{
	TrimString(id);
	ReplaceString(id, maxlen, "STEAM_0:", "STEAM_1:");
}

void LoadList()
{
	g_Allowed.Clear();
	File f = OpenFile(g_sPath, "r");
	if (f == null)
	{
		LogMessage("whitelist.txt not found - server is OPEN to everyone");
		return;
	}
	char line[192], id[64];
	while (f.ReadLine(line, sizeof(line)))
	{
		int c = StrContains(line, "//");
		if (c != -1) line[c] = '\0';
		TrimString(line);
		if (line[0] == '\0') continue;
		BreakString(line, id, sizeof(id));
		NormalizeId(id, sizeof(id));
		if (id[0] != '\0') g_Allowed.SetValue(id, 1);
	}
	delete f;
	LogMessage("whitelist loaded: %d SteamIDs (%s)", g_Allowed.Size, g_Allowed.Size == 0 ? "OPEN to everyone" : "enforced");
}

bool IsAllowed(int client)
{
	if (!g_cvEnable.BoolValue || g_Allowed.Size == 0) return true;
	if (GetUserAdmin(client) != INVALID_ADMIN_ID) return true;
	char id[64];
	if (!GetClientAuthId(client, AuthId_Steam2, id, sizeof(id))) return false;
	NormalizeId(id, sizeof(id));
	int v;
	return g_Allowed.GetValue(id, v);
}

public void OnClientPostAdminCheck(int client)
{
	if (IsFakeClient(client)) return;
	if (!IsAllowed(client))
	{
		LogMessage("whitelist: rejected %L", client);
		KickClient(client, "私人服务器 / Private server - your SteamID is not on the whitelist.");
	}
}

bool AppendId(const char[] id, const char[] note)
{
	File f = OpenFile(g_sPath, "a");
	if (f == null) return false;
	if (note[0] != '\0') f.WriteLine("%s  // %s", id, note);
	else f.WriteLine("%s", id);
	delete f;
	return true;
}

public Action Cmd_Add(int client, int args)
{
	if (args < 1) { ReplyToCommand(client, "[WL] usage: sm_wl_add <#userid|name>"); return Plugin_Handled; }
	char arg[MAX_TARGET_LENGTH];
	GetCmdArg(1, arg, sizeof(arg));
	int target = FindTarget(client, arg, true, false);
	if (target == -1) return Plugin_Handled;
	char id[64], name[MAX_NAME_LENGTH];
	if (!GetClientAuthId(target, AuthId_Steam2, id, sizeof(id))) { ReplyToCommand(client, "[WL] cannot read SteamID"); return Plugin_Handled; }
	NormalizeId(id, sizeof(id));
	GetClientName(target, name, sizeof(name));
	int v;
	if (g_Allowed.GetValue(id, v)) { ReplyToCommand(client, "[WL] %s (%s) already whitelisted", name, id); return Plugin_Handled; }
	if (AppendId(id, name)) { g_Allowed.SetValue(id, 1); ReplyToCommand(client, "[WL] added %s (%s)", name, id); LogMessage("whitelist: %L added %s (%s)", client, name, id); }
	else ReplyToCommand(client, "[WL] failed to write whitelist.txt");
	return Plugin_Handled;
}

public Action Cmd_AddId(int client, int args)
{
	if (args < 1) { ReplyToCommand(client, "[WL] usage: sm_wl_addid <STEAM_1:x:y> [note]"); return Plugin_Handled; }
	char id[64], note[96] = "";
	GetCmdArg(1, id, sizeof(id));
	NormalizeId(id, sizeof(id));
	if (StrContains(id, "STEAM_1:") != 0) { ReplyToCommand(client, "[WL] SteamID must look like STEAM_1:x:y"); return Plugin_Handled; }
	if (args >= 2) GetCmdArg(2, note, sizeof(note));
	int v;
	if (g_Allowed.GetValue(id, v)) { ReplyToCommand(client, "[WL] %s already whitelisted", id); return Plugin_Handled; }
	if (AppendId(id, note)) { g_Allowed.SetValue(id, 1); ReplyToCommand(client, "[WL] added %s", id); LogMessage("whitelist: %L added %s", client, id); }
	else ReplyToCommand(client, "[WL] failed to write whitelist.txt");
	return Plugin_Handled;
}

public Action Cmd_Del(int client, int args)
{
	if (args < 1) { ReplyToCommand(client, "[WL] usage: sm_wl_del <STEAM_1:x:y>"); return Plugin_Handled; }
	char id[64];
	GetCmdArg(1, id, sizeof(id));
	NormalizeId(id, sizeof(id));
	File f = OpenFile(g_sPath, "r");
	if (f == null) { ReplyToCommand(client, "[WL] whitelist.txt not found"); return Plugin_Handled; }
	ArrayList keep = new ArrayList(192);
	char line[192], cur[64];
	bool removed = false;
	while (f.ReadLine(line, sizeof(line)))
	{
		int len = strlen(line);
		while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r')) line[--len] = '\0';
		strcopy(cur, sizeof(cur), line);
		int c = StrContains(cur, "//");
		if (c != -1) cur[c] = '\0';
		TrimString(cur);
		char tok[64];
		BreakString(cur, tok, sizeof(tok));
		NormalizeId(tok, sizeof(tok));
		if (tok[0] != '\0' && StrEqual(tok, id)) { removed = true; continue; }
		keep.PushString(line);
	}
	delete f;
	if (!removed) { delete keep; ReplyToCommand(client, "[WL] %s not in whitelist", id); return Plugin_Handled; }
	f = OpenFile(g_sPath, "w");
	if (f == null) { delete keep; ReplyToCommand(client, "[WL] cannot write whitelist.txt"); return Plugin_Handled; }
	for (int i = 0; i < keep.Length; i++) { keep.GetString(i, line, sizeof(line)); f.WriteLine("%s", line); }
	delete f; delete keep;
	LoadList();
	ReplyToCommand(client, "[WL] removed %s", id);
	LogMessage("whitelist: %L removed %s", client, id);
	return Plugin_Handled;
}

public Action Cmd_List(int client, int args)
{
	ReplyToCommand(client, "[WL] enabled=%d, %d SteamIDs%s", g_cvEnable.IntValue, g_Allowed.Size, g_Allowed.Size == 0 ? " (empty = open to everyone)" : "");
	StringMapSnapshot snap = g_Allowed.Snapshot();
	char id[64];
	for (int i = 0; i < snap.Length; i++) { snap.GetKey(i, id, sizeof(id)); ReplyToCommand(client, "  %s", id); }
	delete snap;
	return Plugin_Handled;
}

public Action Cmd_Reload(int client, int args)
{
	LoadList();
	ReplyToCommand(client, "[WL] reloaded: %d SteamIDs", g_Allowed.Size);
	return Plugin_Handled;
}
