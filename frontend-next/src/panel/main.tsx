import { createRoot } from 'react-dom/client';
import { TwitchAuthStore } from '../auth';
import { IdentityBootstrap, type IdentityHelper } from '../skillgames/identity';
import { configuredApiOrigin } from '../skillgames/origin';
import { PanelController } from './controller';
import { HttpPanelTransport } from './transport';
import { PanelUsage } from './usage';
import { PanelApp } from './PanelApp';
import { EquipmentView } from './EquipmentView';
import './style.css';
declare global { interface Window { Twitch?: { ext?: IdentityHelper } } }
const auth = new TwitchAuthStore();
const identity = new IdentityBootstrap(auth, configuredApiOrigin);
const usage = new PanelUsage({ auth, identity, baseUrl: configuredApiOrigin, surface: /panel-mobile\.html$/.test(location.pathname) ? 'mobile' : 'desktop' });
const controller = new PanelController(new HttpPanelTransport(configuredApiOrigin, auth), auth, identity, Date.now, usage);
if (window.Twitch?.ext) identity.attach(window.Twitch.ext);
const root = document.getElementById('panel-root');
if (!root) throw new Error('Panel root is missing');
createRoot(root).render(<PanelApp controller={controller} identity={identity} Equipment={EquipmentView} combat />);
