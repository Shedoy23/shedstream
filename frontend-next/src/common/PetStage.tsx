export interface PetItem { item_id: string; name: string; slot?: string; rarity?: string; emoji?: string; svg_path?: string | null; png_path?: string | null; price_crustics?: number; owned?: boolean }
export function petPicture(item: PetItem) {
  if (item.svg_path?.trim()) {
    const source = item.svg_path.trim();
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(source.startsWith('<svg') ? source : `<svg viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg">${source}</svg>`);
  }
  return item.png_path || undefined;
}
export function PetIcon({ item }: { item: PetItem }) { return item.png_path ? <img className="pet-icon" src={item.png_path} alt="" /> : <span aria-hidden="true">{item.emoji || '🎁'}</span>; }
export function PetStage({ pet, equipped }: { pet?: { pet_type?: string; name?: string | null }; equipped: Record<string, PetItem> }) {
  const hatched = pet?.pet_type && pet.pet_type !== 'egg', skin = equipped.body?.item_id.startsWith('skin_') ? equipped.body : undefined;
  const layer = (item: PetItem) => petPicture(item) ? <img src={petPicture(item)} alt="" draggable={false} /> : null;
  return <div className={`pet-stage ${equipped.background ? 'pet-stage--' + equipped.background.item_id : ''}`}>
    {equipped.aura && <div className="pet-stage-aura">{Array.from({ length: 6 }, (_, i) => <span className={`pet-particle pet-particle-${i}`} key={i}>{layer(equipped.aura)}</span>)}</div>}
    {!hatched ? <div className="pet-egg">🥚</div> : <>{skin ? <img className="pet-creature" src={skin.png_path || undefined} alt="Питомец" draggable={false} /> : <div className="pet-empty" aria-label="Выбери облик в магазине" />}
      {['body', 'face', 'head', 'accessory'].filter(slot => equipped[slot] && !(slot === 'body' && skin)).map(slot => <div key={slot} className={`pet-layer pet-layer-${slot}`}>{layer(equipped[slot])}</div>)}
    </>}
  </div>;
}
