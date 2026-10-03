import { PanelApp } from '../panel/PanelApp';
import { EquipmentView } from '../panel/EquipmentView';
import type { PanelController } from '../panel/controller';
import type { IdentityBootstrap } from '../skillgames/identity';
export default function BannerlordEntry({ controller, identity }: { controller: PanelController; identity: IdentityBootstrap }) { return <PanelApp controller={controller} identity={identity} Equipment={EquipmentView} embedded combat party tournament full />; }
