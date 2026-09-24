"""Curated native modes shared by the API, persistence and switching service.

IDs, names and base modes checked against Valve's installed update/scripts/
gamemodes.txt and resource/l4d360ui_tu_{english,schinese}.txt (2026-09-24).
mutation10 has an explicit finale mapping in update/missions/campaign1.txt.
This catalog describes game rules, not the current plugin-adjusted player limit.
"""
from enum import Enum

MODES = (
    {'id': 'coop', 'name': '战役', 'description': '合作推进战役章节。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '基础模式', 'base': 'coop', 'english': 'Campaign'},
    {'id': 'realism', 'name': '写实', 'description': '合作战役，使用写实规则。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '基础模式', 'base': 'realism', 'english': 'Realism'},
    {'id': 'versus', 'name': '对抗', 'description': '玩家分为生还者与感染者两队对抗。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '基础模式', 'base': 'versus', 'english': 'Versus'},
    {'id': 'survival', 'name': '生存', 'description': '在固定场地抵御感染者，挑战存活时间。', 'map': 'c1m4_atrium', 'map_name': '死亡中心 · 中庭', 'group': '基础模式', 'base': 'survival', 'english': 'Survival'},
    {'id': 'scavenge', 'name': '清道夫', 'description': '两队轮流收集汽油与阻止对方收集。', 'map': 'c1m4_atrium', 'map_name': '死亡中心 · 中庭', 'group': '基础模式', 'base': 'scavenge', 'english': 'Scavenge'},
    {'id': 'mutation1', 'name': '孤身一人', 'english': 'Last Man on Earth', 'description': '单人战役挑战，面对特殊感染者。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 1},
    {'id': 'mutation2', 'name': '猎头者', 'english': 'Headshot!', 'description': '合作战役，普通感染者需爆头或斩首击杀。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation3', 'name': '血流不止', 'english': 'Bleed Out', 'description': '合作战役，依靠持续流失的临时生命值生存。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation4', 'name': '绝境求生', 'english': 'Hard Eight', 'description': '合作战役，同时面对更多特殊感染者。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation5', 'name': '四剑客', 'english': 'Four Swordsmen', 'description': '合作战役，仅用武士刀迎战特殊感染者。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation7', 'name': '肢解大屠杀', 'english': 'Chainsaw Massacre', 'description': '合作战役，使用电锯突破感染者。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation8', 'name': '钢铁侠', 'english': 'Iron Man', 'description': '写实规则的战役挑战，团灭后重新开始。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation9', 'name': '侏儒卫队', 'english': 'Last Gnome On Earth', 'description': '合作战役，携带并保护小侏儒。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation10', 'name': '单人房间', 'english': 'Room For One', 'description': '仅战役终章；多人竞速，只有一人能够逃离。', 'map': 'c1m4_atrium', 'map_name': '死亡中心 · 中庭', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation11', 'name': '没有救赎！', 'english': 'Healthpackalypse!', 'description': '对抗规则，缺少常规治疗补给。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'versus', 'native_players': 8},
    {'id': 'mutation12', 'name': '写实对抗', 'english': 'Realism Versus', 'description': '对抗模式结合写实规则。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'versus', 'native_players': 8},
    {'id': 'mutation13', 'name': '限量发放', 'english': 'Follow the Liter', 'description': '清道夫规则，分批收集汽油罐。', 'map': 'c1m4_atrium', 'map_name': '死亡中心 · 中庭', 'group': '突变模式', 'base': 'scavenge', 'native_players': 8},
    {'id': 'mutation14', 'name': '四分五裂', 'english': 'Gib Fest', 'description': '合作战役，使用无限弹药的 M60。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation15', 'name': '生还者对抗', 'english': 'Versus Survival', 'description': '生存守点，感染者由玩家控制。', 'map': 'c1m4_atrium', 'map_name': '死亡中心 · 中庭', 'group': '突变模式', 'base': 'survival', 'native_players': 8},
    {'id': 'mutation16', 'name': '狩猎盛宴', 'english': 'Hunting Party', 'description': '合作战役，迎战 Hunter 特感队伍。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
    {'id': 'mutation17', 'name': '孤胆枪手', 'english': 'Lone Gunman', 'description': '单人战役，使用马格南手枪求生。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 1},
    {'id': 'mutation18', 'name': '溢血抗争', 'english': 'Bleed Out Versus', 'description': '对抗规则，临时生命值持续流失。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'versus', 'native_players': 8},
    {'id': 'mutation19', 'name': 'Taaannnk!!', 'english': 'Taaannnk!!', 'description': '对抗规则，感染者队伍使用 Tank。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'versus', 'native_players': 8},
    {'id': 'mutation20', 'name': '疗伤小侏儒', 'english': 'Healing Gnome', 'description': '合作战役，借助小侏儒恢复生命。', 'map': 'c1m1_hotel', 'map_name': '死亡中心 · 旅馆', 'group': '突变模式', 'base': 'coop', 'native_players': 4},
)

MODE_IDS = frozenset(mode['id'] for mode in MODES)
GameMode = Enum('GameMode', {mode: mode for mode in MODE_IDS}, type=str)
