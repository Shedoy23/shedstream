import type {HeroReply} from './contracts';
import type {ForgeItem} from './forge';
export function observedEquipment(hero:HeroReply|null):[string,ForgeItem][]{const equipment=hero?.equipment;return equipment&&typeof equipment==='object'&&!Array.isArray(equipment)?Object.entries(equipment).filter((row):row is [string,ForgeItem]=>!!row[1]&&typeof row[1]==='object'&&typeof row[1].item_id==='string'):[];}
export interface ShopItem {catalog_type:string;entry_id:string;action_type?:string;name?:string;description?:string;price?:unknown}
export interface ShopReply {success:boolean;items?:ShopItem[];message?:string}
export interface StatusReply {success:boolean;online:boolean;last_seen?:number|null;age_seconds?:number|null}
export interface GoldPreset {crusticov:number;dinars:number}
export const isGoldPreset=(value:unknown):value is GoldPreset=>{if(!value||typeof value!=='object')return false;const o=value as Partial<GoldPreset>;return Number.isSafeInteger(o.crusticov)&&o.crusticov!>=0&&Number.isSafeInteger(o.dinars)&&o.dinars!>0;};
