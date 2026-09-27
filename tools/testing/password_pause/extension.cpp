// SPDX-License-Identifier: GPL-3.0-or-later
#include "smsdk_ext.h"
#include <cstring>

static cell_t SetPasswordPluginPaused(IPluginContext *context, const cell_t *params)
{
    IPlugin *target = nullptr;
    IPluginIterator *iterator = plsys->GetPluginIterator();
    while (iterator->MorePlugins()) {
        IPlugin *plugin = iterator->GetPlugin();
        if (std::strcmp(plugin->GetFilename(), "panel_join_password.smx") == 0) {
            target = plugin;
            break;
        }
        iterator->NextPlugin();
    }
    iterator->Release();
    if (!target)
        return context->ThrowNativeError("Password test target is not loaded");
    const bool paused = params[1] != 0;
    const PluginStatus wanted = paused ? Plugin_Paused : Plugin_Running;
    if (target->GetStatus() != wanted && !target->SetPauseState(paused))
        return context->ThrowNativeError("Password test target cannot change pause state");
    return static_cast<cell_t>(target->GetStatus());
}

static const sp_nativeinfo_t natives[] = {
    {"PanelPasswordTestPause", SetPasswordPluginPaused},
    {nullptr, nullptr}
};

class PasswordPauseTest final : public SDKExtension
{
public:
    bool SDK_OnLoad(char *, size_t, bool) override
    {
        sharesys->AddNatives(myself, natives);
        return true;
    }
};

static PasswordPauseTest extension;
SMEXT_LINK(&extension)
