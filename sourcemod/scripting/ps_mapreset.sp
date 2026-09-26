#include <sourcemod>
#include <ps_natives>

#pragma newdecls required
#pragma semicolon 1

#define PLUGIN_VERSION "1.0"

// Resets every player's points to l4d2_points_start at the start of each map,
// so every campaign leg begins from the same budget instead of carrying a
// balance across the whole session.
//
// A player who disconnects and rejoins during the SAME map is not reset again
// (that would let anyone refill their points by rejoining). This is tracked per
// SteamID and the record is cleared on map change.
//
// The points row is loaded from SQL asynchronously, so we poll
// PS_GetDataLoadState instead of resetting blindly on a fixed delay - writing
// before the row is in would be overwritten by the load.

public Plugin myinfo =
{
	name = "[PS] Map Reset",
	author = "local",
	description = "Reset every player's points to the starting value on each map",
	version = PLUGIN_VERSION,
	url = ""
};

ConVar g_cvEnable;
ConVar g_cvStart;

StringMap g_smDone;            // SteamID -> already reset on this map
int       g_iTries[MAXPLAYERS + 1];

public void OnPluginStart()
{
	g_cvEnable = CreateConVar("sm_ps_mapreset", "1", "1 = reset everyone's points at the start of each map, 0 = off", _, true, 0.0, true, 1.0);

	g_cvStart = FindConVar("l4d2_points_start");
	if (g_cvStart == null)
		SetFailState("l4d2_points_start not found - is l4d2_points_system running?");

	g_smDone = new StringMap();

	RegAdminCmd("sm_ps_resetnow", Cmd_ResetNow, ADMFLAG_ROOT, "Reset every player's points to the starting value immediately");
}

public void OnMapStart()
{
	// new leg -> everyone is eligible again
	g_smDone.Clear();

	if (!g_cvEnable.BoolValue)
		return;

	// players already connected do not fire OnClientPostAdminCheck on a map
	// change, so kick off polling for them here
	for (int i = 1; i <= MaxClients; i++)
		if (IsClientInGame(i) && !IsFakeClient(i))
			StartPoll(i);
}

public void OnClientPostAdminCheck(int client)
{
	if (g_cvEnable.BoolValue && !IsFakeClient(client))
		StartPoll(client);
}

void StartPoll(int client)
{
	g_iTries[client] = 0;
	CreateTimer(2.0, Timer_Poll, GetClientUserId(client), TIMER_REPEAT | TIMER_FLAG_NO_MAPCHANGE);
}

Action Timer_Poll(Handle timer, int userid)
{
	int client = GetClientOfUserId(userid);
	if (client <= 0 || !IsClientInGame(client) || IsFakeClient(client))
		return Plugin_Stop;

	if (++g_iTries[client] > 15)    // give up after ~30s
		return Plugin_Stop;

	if (!PS_GetDataLoadState(client))
		return Plugin_Continue;     // SQL row still loading

	DoReset(client);
	return Plugin_Stop;
}

void DoReset(int client)
{
	char sid[40];
	if (!GetClientAuthId(client, AuthId_Steam2, sid, sizeof(sid)))
		return;

	bool seen;
	if (g_smDone.GetValue(sid, seen))
		return;                     // already reset on this map

	g_smDone.SetValue(sid, true);

	int start = g_cvStart.IntValue;
	PS_SetPoints(client, start);
	PrintToChat(client, "[PS] 新关卡开始，积分重置为 \x04%d\x01", start);
}

public Action Cmd_ResetNow(int client, int args)
{
	int start = g_cvStart.IntValue;
	int n = 0;

	for (int i = 1; i <= MaxClients; i++)
	{
		if (!IsClientInGame(i) || IsFakeClient(i)) continue;
		if (!PS_GetDataLoadState(i)) continue;

		PS_SetPoints(i, start);
		n++;

		char sid[40];
		if (GetClientAuthId(i, AuthId_Steam2, sid, sizeof(sid)))
			g_smDone.SetValue(sid, true);
	}

	ReplyToCommand(client, "[PS] 已把 %d 名玩家的积分重置为 %d", n, start);
	return Plugin_Handled;
}
