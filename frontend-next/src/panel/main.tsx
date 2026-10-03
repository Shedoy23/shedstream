import { createRoot } from 'react-dom/client';
import { TwitchAuthStore } from '../auth';
import { devHelperFromLocation } from '../devAuth';
import { IdentityBootstrap, type IdentityHelper } from '../skillgames/identity';
import { configuredApiOrigin } from '../skillgames/origin';
import { PanelController } from './controller';
import { HttpPanelTransport } from './transport';
import { ViewerRuntime, type ViewerHelper } from '../common/runtime';
import { ViewerShell } from '../common/ViewerShell';
import { RimworldController } from '../rimworld/controller';
import {ColonyController} from '../colony/controller';
import './style.css';
declare global { interface Window { Twitch?: { ext?: IdentityHelper } } }
const auth = new TwitchAuthStore();
const identity = new IdentityBootstrap(auth, configuredApiOrigin, fetch, { panelProtocol: true });
const runtime = new ViewerRuntime(auth, identity, { baseUrl: configuredApiOrigin, surface: /panel-mobile\.html$/.test(location.pathname) ? 'mobile' : 'desktop' });
const rimworld = new RimworldController(runtime);
const colony = new ColonyController(runtime);
const controller = new PanelController(new HttpPanelTransport(configuredApiOrigin, auth), auth, identity, Date.now, runtime.usage);
controller.useHostUsage();
controller.useHostBalance({ refresh: () => runtime.snapshot().client?.refreshUser() || Promise.resolve(), points: () => { const value = runtime.snapshot().stats?.points; return typeof value === 'number' ? value : null; } });
controller.bindHost(runtime);
runtime.start();
// 03.10: the official Twitch helper script defines window.Twitch.ext even in a plain browser
// tab, so "Twitch exists" cannot mean "inside Twitch". Dev preview = ?dev_jwt= AND the page is
// not framed (Twitch always frames extensions). The server still verifies the token on every call.
const devPreview = window.self === window.top ? devHelperFromLocation(location.search, false) : null;
if (devPreview) { runtime.attach(devPreview as ViewerHelper); identity.attach(devPreview); }
else if (window.Twitch?.ext) { runtime.attach(window.Twitch.ext as ViewerHelper); identity.attach(window.Twitch.ext); }
const root = document.getElementById('panel-root');
if (!root) throw new Error('Panel root is missing');
createRoot(root).render(<ViewerShell controller={controller} identity={identity} auth={auth} runtime={runtime} rimworld={rimworld} colony={colony} />);
