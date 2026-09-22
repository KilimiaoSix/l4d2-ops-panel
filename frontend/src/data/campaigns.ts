/** The 14 official campaigns: [first map, display name]. Custom campaigns are appended from the addon list. */
export const CAMPAIGNS: [string, string][] = [
  ['c1m1_hotel', '1 死亡中心'], ['c2m1_highway', '2 黑色狂欢节'], ['c3m1_plankcountry', '3 沼泽激战'], ['c4m1_milltown_a', '4 暴风骤雨'],
  ['c5m1_waterfront', '5 教区'], ['c6m1_riverbank', '6 牺牲'], ['c7m1_docks', '7 短暂时刻'], ['c8m1_apartment', '8 毫不留情'],
  ['c9m1_alleys', '9 坠机险途'], ['c10m1_caves', '10 死亡丧钟'], ['c11m1_greenhouse', '11 寂静时分'], ['c12m1_hilltop', '12 血腥收获'],
  ['c13m1_alpinecreek', '13 寒冷溪流'], ['c14m1_junkyard', '14 最后一战'],
]

export const DIFFICULTY_NAMES: Record<string, string> = { easy: '简单', normal: '普通', hard: '高级', impossible: '专家' }
export const PRESETS = ['auto', 'te8', 'te12', 'te16'] as const
