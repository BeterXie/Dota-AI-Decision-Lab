// Dota 2 assets, hero portraits & pro team logos

import { getOfficialTeamLogoUrlByName } from "./officialVisuals";

const HERO_NAME_TO_SHORT: Record<string, string> = {
  "anti-mage": "antimage",
  "antimage": "antimage",
  "axe": "axe",
  "bane": "bane",
  "bloodseeker": "bloodseeker",
  "crystal maiden": "crystal_maiden",
  "crystal_maiden": "crystal_maiden",
  "drow ranger": "drow_ranger",
  "drow_ranger": "drow_ranger",
  "earthshaker": "earthshaker",
  "juggernaut": "juggernaut",
  "mirana": "mirana",
  "morphling": "morphling",
  "shadow fiend": "nevermore",
  "nevermore": "nevermore",
  "phantom assassin": "phantom_assassin",
  "phantom_assassin": "phantom_assassin",
  "puck": "puck",
  "pudge": "pudge",
  "razor": "razor",
  "sand king": "sand_king",
  "sand_king": "sand_king",
  "storm spirit": "storm_spirit",
  "storm_spirit": "storm_spirit",
  "sven": "sven",
  "tiny": "tiny",
  "vengeful spirit": "vengefulspirit",
  "vengefulspirit": "vengefulspirit",
  "windranger": "windrunner",
  "windrunner": "windrunner",
  "zeus": "zuus",
  "zuus": "zuus",
  "kunkka": "kunkka",
  "lina": "lina",
  "lion": "lion",
  "shadow shaman": "shadow_shaman",
  "shadow_shaman": "shadow_shaman",
  "slardar": "slardar",
  "tidehunter": "tidehunter",
  "witch doctor": "witch_doctor",
  "witch_doctor": "witch_doctor",
  "lich": "lich",
  "riki": "riki",
  "enigma": "enigma",
  "tinker": "tinker",
  "sniper": "sniper",
  "necrophos": "necrolyte",
  "necrolyte": "necrolyte",
  "warlock": "warlock",
  "beastmaster": "beastmaster",
  "queen of pain": "queenofpain",
  "queenofpain": "queenofpain",
  "venomancer": "venomancer",
  "faceless void": "faceless_void",
  "faceless_void": "faceless_void",
  "wraith king": "skeleton_king",
  "skeleton_king": "skeleton_king",
  "death prophet": "death_prophet",
  "death_prophet": "death_prophet",
  "phantom lancer": "phantom_lancer",
  "phantom_lancer": "phantom_lancer",
  "pugna": "pugna",
  "templar assassin": "templar_assassin",
  "templar_assassin": "templar_assassin",
  "viper": "viper",
  "luna": "luna",
  "dragon knight": "dragon_knight",
  "dragon_knight": "dragon_knight",
  "dazzle": "dazzle",
  "clockwerk": "rattletrap",
  "rattletrap": "rattletrap",
  "leshrac": "leshrac",
  "nature's prophet": "furion",
  "furion": "furion",
  "lifestealer": "life_stealer",
  "life_stealer": "life_stealer",
  "dark seer": "dark_seer",
  "dark_seer": "dark_seer",
  "clinkz": "clinkz",
  "omniknight": "omniknight",
  "enchantress": "enchantress",
  "huskar": "huskar",
  "night stalker": "night_stalker",
  "night_stalker": "night_stalker",
  "broodmother": "broodmother",
  "bounty hunter": "bounty_hunter",
  "bounty_hunter": "bounty_hunter",
  "weaver": "weaver",
  "jakiro": "jakiro",
  "batrider": "batrider",
  "chen": "chen",
  "spectre": "spectre",
  "ancient apparation": "ancient_apparition",
  "ancient_apparition": "ancient_apparition",
  "doom": "doom_bringer",
  "doom_bringer": "doom_bringer",
  "ursa": "ursa",
  "spirit breaker": "spirit_breaker",
  "spirit_breaker": "spirit_breaker",
  "gyrocopter": "gyrocopter",
  "alchemist": "alchemist",
  "invoker": "invoker",
  "silencer": "silencer",
  "outworld destroyer": "obsidian_destroyer",
  "obsidian_destroyer": "obsidian_destroyer",
  "lycan": "lycan",
  "brewmaster": "brewmaster",
  "shadow demon": "shadow_demon",
  "shadow_demon": "shadow_demon",
  "lone druid": "lone_druid",
  "lone_druid": "lone_druid",
  "chaos knight": "chaos_knight",
  "chaos_knight": "chaos_knight",
  "meepo": "meepo",
  "treant protector": "treant",
  "treant": "treant",
  "ogre magi": "ogre_magi",
  "ogre_magi": "ogre_magi",
  "undying": "undying",
  "rubick": "rubick",
  "disruptor": "disruptor",
  "nyx assassin": "nyx_assassin",
  "nyx_assassin": "nyx_assassin",
  "naga siren": "naga_siren",
  "naga_siren": "naga_siren",
  "keeper of the light": "keeper_of_the_light",
  "keeper_of_the_light": "keeper_of_the_light",
  "io": "wisp",
  "wisp": "wisp",
  "visage": "visage",
  "slark": "slark",
  "medusa": "medusa",
  "troll warlord": "troll_warlord",
  "troll_warlord": "troll_warlord",
  "centaur warrunner": "centaur",
  "centaur": "centaur",
  "magnus": "magnataur",
  "timbersaw": "shredder",
  "shredder": "shredder",
  "bristleback": "bristleback",
  "tusk": "tusk",
  "skywrath mage": "skywrath_mage",
  "skywrath_mage": "skywrath_mage",
  "abaddon": "abaddon",
  "elder titan": "elder_titan",
  "elder_titan": "elder_titan",
  "legion commander": "legion_commander",
  "legion_commander": "legion_commander",
  "techies": "techies",
  "ember spirit": "ember_spirit",
  "ember_spirit": "ember_spirit",
  "earth spirit": "earth_spirit",
  "earth_spirit": "earth_spirit",
  "underlord": "abyssal_underlord",
  "abyssal_underlord": "abyssal_underlord",
  "terrorblade": "terrorblade",
  "phoenix": "phoenix",
  "oracle": "oracle",
  "winter wyvern": "winter_wyvern",
  "winter_wyvern": "winter_wyvern",
  "arc warden": "arc_warden",
  "arc_warden": "arc_warden",
  "monkey king": "monkey_king",
  "monkey_king": "monkey_king",
  "willow": "dark_willow",
  "dark_willow": "dark_willow",
  "pangolier": "pangolier",
  "grimstroke": "grimstroke",
  "hoodwink": "hoodwink",
  "void spirit": "void_spirit",
  "void_spirit": "void_spirit",
  "snapfire": "snapfire",
  "mars": "mars",
  "dawnbreaker": "dawnbreaker",
  "marci": "marci",
  "primal beast": "primal_beast",
  "primal_beast": "primal_beast",
  "muerta": "muerta",
  "ringmaster": "ringmaster",
  "kez": "kez"
};

export function getHeroShortName(name: string | null | undefined): string | null {
  if (!name) return null;
  const normalized = name.trim().toLowerCase();
  if (HERO_NAME_TO_SHORT[normalized]) {
    return HERO_NAME_TO_SHORT[normalized];
  }
  return normalized.replace(/[^a-z0-9]/g, "_").replace(/_+/g, "_");
}

export function getHeroPortraitUrl(heroName: string | null | undefined): string | null {
  const shortName = getHeroShortName(heroName);
  if (!shortName) return null;
  return `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${shortName}.png`;
}

export function getTeamLogoUrl(teamName: string | null | undefined): string | null {
  return getOfficialTeamLogoUrlByName(teamName);
}

export function getPositionLabel(pos: number): string {
  switch (pos) {
    case 1:
      return "P1";
    case 2:
      return "P2";
    case 3:
      return "P3";
    case 4:
      return "P4";
    case 5:
      return "P5";
    default:
      return `P${pos}`;
  }
}

export function getPositionRole(pos: number): string {
  switch (pos) {
    case 1:
      return "Carry";
    case 2:
      return "Mid";
    case 3:
      return "Offlane";
    case 4:
      return "Soft Sup";
    case 5:
      return "Hard Sup";
    default:
      return "Flex";
  }
}

export function getTeamAbbreviation(name: string | null | undefined): string {
  if (!name) return "UNK";
  const upper = name.toUpperCase().trim();
  if (upper.includes("SPIRIT")) return "TS";
  if (upper.includes("AURORA")) return "AUR";
  if (upper.includes("XTREME")) return "XG";
  if (upper.includes("TUNDRA")) return "TUN";
  if (upper.includes("LIQUID")) return "TL";
  if (upper.includes("FALCONS")) return "FLC";
  if (upper.includes("GLADIATORS")) return "GG";
  if (upper.includes("BETBOOM")) return "BB";
  if (upper.includes("GAIMIN")) return "GG";
  if (upper.includes("PARIVISION")) return "PV";
  if (upper.includes("HEROIC")) return "HER";
  return name.slice(0, 3).toUpperCase();
}
