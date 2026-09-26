/* GeoDados DF — painel 3D dos equipamentos de fiscalização eletrônica
   Motor: CesiumJS (o mesmo do God's Eye View). */
"use strict";

const TYPES = {
  CE: { name: "Controlador eletrônico", color: "#C0801C", prefix: "KR" },
  RE: { name: "Redutor eletrônico de velocidade", color: "#4A90E0", prefix: "RE" },
  NM: { name: "Não metrológico", color: "#D15A7F", prefix: "FI" },
};
const TYPE_CSS = { CE: "var(--ce)", RE: "var(--re)", NM: "var(--nm)" };
const DIRS = {
  "NORTE/SUL": "Norte → Sul", "SUL/NORTE": "Sul → Norte",
  "LESTE/OESTE": "Leste → Oeste", "OESTE/LESTE": "Oeste → Leste",
  "OUTRO": "Outro / via nomeada",
};
const PAGE = 120;

const state = {
  items: [], byId: new Map(),
  types: new Set(Object.keys(TYPES)), dirs: new Set(Object.keys(DIRS)), ras: new Set(), q: "",
  selected: null, listLimit: PAGE, has3D: false, tilted: true, cluster: false, base: "sat",
  config: { googleMapsKey: "", cesiumIonToken: "" },
};
const $ = (id) => document.getElementById(id);
let viewer, ds, baseLayers = [], tileset = null, fallbackUsed = false, tileErrors = 0;

/* ---------------- início ---------------- */
window.addEventListener("DOMContentLoaded", boot);

async function boot() {
  let data;
  try {
    const [d, cfg, me] = await Promise.all([
      getJSON("/data/equipamentos.json"), getJSON("/api/config").catch(() => ({})), getJSON("/api/me").catch(() => null),
    ]);
    data = d; Object.assign(state.config, cfg);
    if (me && me.user) $("whoami").textContent = me.user;
  } catch (e) {
    if (e.status === 401) { location.href = "/login"; return; }
    $("loading").textContent = "Não foi possível carregar os dados. Recarregue a página.";
    return;
  }
  state.items = data;
  data.forEach((it) => { state.byId.set(it.id, it); state.ras.add(it.cra); });
  $("totCount").textContent = data.length;

  buildStaticUI();
  try { await initGlobe(); } catch (e) { console.error(e); toast("O globo 3D não pôde ser iniciado neste navegador."); }
  $("loading").hidden = true;
  update();
  fitVisible(0);
}

async function getJSON(url) {
  const r = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!r.ok) { const e = new Error(r.statusText); e.status = r.status; throw e; }
  return r.json();
}

/* ---------------- globo ---------------- */
async function initGlobe() {
  const C = Cesium;
  if (state.config.cesiumIonToken) C.Ion.defaultAccessToken = state.config.cesiumIonToken;
  if (state.config.googleMapsKey) C.GoogleMaps.defaultApiKey = state.config.googleMapsKey;

  viewer = new C.Viewer("map", {
    baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
    navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
    infoBox: false, selectionIndicator: false, requestRenderMode: true, maximumRenderTimeChange: Infinity,
  });
  const scene = viewer.scene;
  scene.globe.baseColor = C.Color.fromCssColorString("#1d2a33");
  scene.globe.depthTestAgainstTerrain = false;
  scene.skyAtmosphere.show = true;
  scene.fog.enabled = true;
  viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  setBase("sat");

  // visão inicial: DF visto do sul, inclinado
  viewer.camera.setView({
    destination: C.Cartesian3.fromDegrees(-47.93, -16.28, 42000),
    orientation: { heading: 0, pitch: C.Math.toRadians(-42), roll: 0 },
  });

  ds = new C.CustomDataSource("equipamentos");
  await viewer.dataSources.add(ds);
  const icons = {};
  for (const k of Object.keys(TYPES)) icons[k] = { n: svgURL(iconSVG(k)), s: svgURL(iconSVG(k, { selected: true })) };
  state.icons = icons;

  for (const it of state.items) {
    it.entity = ds.entities.add({
      id: it.id,
      position: C.Cartesian3.fromDegrees(it.lon, it.lat),
      billboard: {
        image: icons[it.t].n, width: 28, height: 28,
        heightReference: C.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        scaleByDistance: new C.NearFarScalar(1500, 1.15, 120000, 0.7),
      },
      label: {
        text: it.id, show: false, font: "500 13px 'IBM Plex Mono', monospace",
        fillColor: C.Color.WHITE, outlineColor: C.Color.fromCssColorString("#0B1014"), outlineWidth: 4,
        style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -30),
        heightReference: C.HeightReference.CLAMP_TO_GROUND, disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  // agrupamento
  const cl = ds.clustering;
  cl.pixelRange = 38; cl.minimumClusterSize = 3; cl.enabled = false;
  const clusterIcons = new Map();
  cl.clusterEvent.addEventListener((entities, cluster) => {
    const n = entities.length;
    if (!clusterIcons.has(n)) clusterIcons.set(n, clusterIcon(n));
    cluster.label.show = false;
    cluster.billboard.show = true;
    cluster.billboard.image = clusterIcons.get(n);
    cluster.billboard.width = n >= 100 ? 46 : n >= 10 ? 38 : 32;
    cluster.billboard.height = cluster.billboard.width;
    cluster.billboard.verticalOrigin = C.VerticalOrigin.CENTER;
    cluster.billboard.disableDepthTestDistance = Number.POSITIVE_INFINITY;
    cluster.billboard.id = entities;
  });

  // interação: passar o mouse e clicar
  const handler = new C.ScreenSpaceEventHandler(scene.canvas);
  let raf = 0, lastMove = null;
  handler.setInputAction((m) => {
    lastMove = m.endPosition;
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; hover(lastMove); });
  }, C.ScreenSpaceEventType.MOUSE_MOVE);
  handler.setInputAction((c) => {
    const p = scene.pick(c.position);
    if (!p || !p.id) return;
    if (Array.isArray(p.id)) return zoomToEntities(p.id);
    if (p.id instanceof C.Entity && state.byId.has(p.id.id)) select(p.id.id, true);
  }, C.ScreenSpaceEventType.LEFT_CLICK);

  // falha na imagem de satélite → mapa básico offline
  viewer.camera.moveEnd.addEventListener(() => scene.requestRender());
}

function hover(pos) {
  const tip = $("tip");
  if (!pos || !viewer) return (tip.hidden = true);
  const p = viewer.scene.pick(pos);
  let html = "";
  if (p && Array.isArray(p.id)) {
    html = `<b>${p.id.length}</b><span>equipamentos · clique para aproximar</span>`;
  } else if (p && p.id && state.byId.has(p.id.id)) {
    const it = state.byId.get(p.id.id);
    html = `<b>${it.id}</b><span>${TYPES[it.t].name} · ${esc(it.ra)}</span>`;
  }
  viewer.scene.canvas.style.cursor = html ? "pointer" : "";
  if (!html) return (tip.hidden = true);
  tip.innerHTML = html;
  const r = viewer.scene.canvas.getBoundingClientRect();
  tip.style.left = r.left + pos.x + "px";
  tip.style.top = r.top + pos.y + "px";
  tip.hidden = false;
}

/* Ícones (opção A): Controlador = câmera no quadrado · Redutor = placa de velocidade no círculo
   · Não metrológico = semáforo no losango. Mesma função para o mapa e para o painel. */
const PICTO = {
  CE: (c) => `<rect x="4" y="8" width="13" height="9" rx="1.6" fill="#fff"/><path d="M17 11l4-2v7l-4-2z" fill="#fff"/><circle cx="9.5" cy="12.5" r="2.4" fill="${c}"/><path d="M6 6.5h4" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>`,
  RE: () => `<circle cx="12" cy="12" r="8.6" fill="#fff" stroke="#D2231E" stroke-width="2.6"/><text x="12" y="15.4" font-family="Arial,Helvetica,sans-serif" font-weight="700" font-size="9.5" fill="#111" text-anchor="middle">60</text>`,
  NM: () => `<rect x="8" y="3.5" width="8" height="17" rx="2.4" fill="#fff"/><circle cx="12" cy="7.3" r="1.9" fill="#D2231E"/><circle cx="12" cy="12" r="1.9" fill="#E8A300"/><circle cx="12" cy="16.7" r="1.9" fill="#1E9E4A"/>`,
};
function iconSVG(k, { color = TYPES[k].color, selected = false, shadow = true } = {}) {
  const pic = (s) => `<g transform="translate(${20 - 12 * s} ${20 - 12 * s}) scale(${s})">${PICTO[k](color)}</g>`;
  const frame = {
    CE: `<rect x="5.5" y="5.5" width="29" height="29" rx="6" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.95)}`,
    RE: `<circle cx="20" cy="20" r="15" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.95)}`,
    NM: `<rect x="8.5" y="8.5" width="23" height="23" rx="4" transform="rotate(45 20 20)" fill="${color}" stroke="#fff" stroke-width="2.5"/>${pic(0.78)}`,
  }[k];
  const halo = selected ? `<circle cx="20" cy="20" r="19.5" fill="#fff" fill-opacity=".4"/>` : "";
  const f = shadow ? `<defs><filter id="sh" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-opacity=".45"/></filter></defs>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="40" height="40">${f}${halo}<g${shadow ? ' filter="url(#sh)"' : ""}>${frame}</g></svg>`;
}
const svgURL = (svg) => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
const icoHTML = (k) => `<span class="ico" aria-hidden="true">${iconSVG(k, { shadow: false })}</span>`;

function clusterIcon(n) {
  const c = document.createElement("canvas"); c.width = c.height = 96;
  const x = c.getContext("2d");
  x.beginPath(); x.arc(48, 48, 44, 0, Math.PI * 2); x.fillStyle = "rgba(20,26,31,.55)"; x.fill();
  x.beginPath(); x.arc(48, 48, 34, 0, Math.PI * 2); x.fillStyle = "#141A1F"; x.fill();
  x.lineWidth = 4; x.strokeStyle = "#FFFFFF"; x.stroke();
  x.fillStyle = "#FFFFFF"; x.font = "700 34px 'Barlow Condensed', Barlow, sans-serif";
  x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(String(n), 48, 50);
  return c.toDataURL();
}

/* ---------------- mapas base e 3D ---------------- */
function setBase(key) {
  const C = Cesium, L = viewer.imageryLayers;
  baseLayers.forEach((l) => L.remove(l, true)); baseLayers = [];
  tileErrors = 0;
  const esri = (svc, max = 19) => new C.UrlTemplateImageryProvider({
    url: `https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`,
    maximumLevel: max, credit: "Imagens © Esri, Maxar, Earthstar Geographics",
  });
  const carto = (style) => new C.UrlTemplateImageryProvider({
    url: `https://{s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}.png`, subdomains: "abcd",
    maximumLevel: 19, credit: "© OpenStreetMap, © CARTO",
  });
  const add = (prov) => { watchErrors(prov); baseLayers.push(L.addImageryProvider(prov, baseLayers.length)); };

  if (key === "sat") add(esri("World_Imagery"));
  if (key === "hib") { add(esri("World_Imagery")); add(esri("Reference/World_Transportation", 18)); add(esri("Reference/World_Boundaries_and_Places", 18)); }
  if (key === "ruas") add(carto("voyager"));
  if (key === "escuro") add(carto("dark_all"));
  if (key === "offline") {
    const lyr = C.ImageryLayer.fromProviderAsync(C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl("Assets/Textures/NaturalEarthII")));
    L.add(lyr, 0); baseLayers.push(lyr);
  }
  state.base = key;
  document.querySelectorAll("#baseSeg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === key)));
  viewer.scene.requestRender();
}

function watchErrors(prov) {
  prov.errorEvent.addEventListener(() => {
    tileErrors++;
    if (tileErrors === 12 && !fallbackUsed) {
      fallbackUsed = true;
      setBase("offline");
      toast("A imagem de satélite não respondeu. Mostrando o mapa básico offline; tente outro mapa base no topo.");
    }
  });
}

async function toggle3D() {
  const C = Cesium, btn = $("btn3d"), scene = viewer.scene;
  if (!state.has3D) {
    btn.disabled = true; btn.textContent = "Carregando…";
    try {
      if (state.config.googleMapsKey || state.config.cesiumIonToken) {
        if (state.config.googleMapsKey) {
          tileset = await C.createGooglePhotorealistic3DTileset({ key: state.config.googleMapsKey });
          scene.globe.show = false;
        } else {
          scene.setTerrain(C.Terrain.fromWorldTerrain());
          tileset = await C.createOsmBuildingsAsync();
        }
        scene.primitives.add(tileset);
        state.has3D = true;
      }
    } catch (e) {
      console.error(e);
      toast("Não foi possível carregar os prédios 3D. Confira a chave configurada no servidor.");
    }
    btn.disabled = false; btn.textContent = "Prédios 3D";
  } else {
    if (tileset) { scene.primitives.remove(tileset); tileset = null; }
    scene.globe.show = true;
    viewer.terrainProvider = new C.EllipsoidTerrainProvider();
    state.has3D = false;
  }
  btn.setAttribute("aria-pressed", String(state.has3D));
  document.querySelectorAll("#baseSeg button").forEach((b) => {
    b.disabled = state.has3D && !!state.config.googleMapsKey;
    b.title = b.disabled ? "Desligue Prédios 3D para trocar o mapa base" : "";
  });
  scene.requestRender();
}

/* ---------------- câmera ---------------- */
function groundHeightGuess() { return state.has3D ? 1100 : 0; }

async function groundHeightAt(lon, lat) {
  const C = Cesium, carto = C.Cartographic.fromDegrees(lon, lat);
  if (!state.has3D) return 0;
  try {
    if (tileset && state.config.googleMapsKey) {
      const [r] = await withTimeout(viewer.scene.sampleHeightMostDetailed([carto]), 2500);
      if (r && Number.isFinite(r.height)) return r.height;
    } else {
      const [r] = await withTimeout(C.sampleTerrainMostDetailed(viewer.terrainProvider, [carto]), 2500);
      if (r && Number.isFinite(r.height)) return r.height;
    }
  } catch { /* usa estimativa */ }
  return 1100;
}
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);

async function flyToItem(it) {
  const C = Cesium, h = await groundHeightAt(it.lon, it.lat);
  const pos = C.Cartesian3.fromDegrees(it.lon, it.lat, h);
  viewer.camera.flyToBoundingSphere(new C.BoundingSphere(pos, 5), {
    offset: new C.HeadingPitchRange(viewer.camera.heading, C.Math.toRadians(state.tilted ? -38 : -89.9), state.tilted ? 520 : 900),
    duration: 1.6,
  });
}

function fitVisible(duration = 1.4) {
  if (!viewer) return;
  const C = Cesium, h = groundHeightGuess();
  const vis = visibleItems();
  if (!vis.length) return;
  const pts = vis.map((it) => C.Cartesian3.fromDegrees(it.lon, it.lat, h));
  const bs = C.BoundingSphere.fromPoints(pts);
  const range = Math.max(bs.radius * 2.4, 1200);
  viewer.camera.flyToBoundingSphere(bs, {
    offset: new C.HeadingPitchRange(0, C.Math.toRadians(state.tilted ? -48 : -89.9), range), duration,
  });
}

function zoomToEntities(ents) {
  const C = Cesium, h = groundHeightGuess();
  const pts = ents.map((e) => { const it = state.byId.get(e.id); return C.Cartesian3.fromDegrees(it.lon, it.lat, h); });
  const bs = C.BoundingSphere.fromPoints(pts);
  viewer.camera.flyToBoundingSphere(bs, { offset: new C.HeadingPitchRange(viewer.camera.heading, C.Math.toRadians(state.tilted ? -50 : -89.9), Math.max(bs.radius * 3, 900)), duration: 1.2 });
}

function toggleTilt() {
  const C = Cesium, scene = viewer.scene, cam = viewer.camera;
  state.tilted = !state.tilted;
  const btn = $("btnTilt");
  btn.setAttribute("aria-pressed", String(state.tilted));
  btn.textContent = state.tilted ? "Inclinada" : "De cima";
  const center = new C.Cartesian2(scene.canvas.clientWidth / 2, scene.canvas.clientHeight / 2);
  let target = state.has3D ? scene.pickPosition(center) : undefined;
  if (!target) target = cam.pickEllipsoid(center, scene.globe.ellipsoid);
  if (!target) return fitVisible();
  const range = C.Cartesian3.distance(cam.positionWC, target);
  cam.flyToBoundingSphere(new C.BoundingSphere(target, 1), {
    offset: new C.HeadingPitchRange(cam.heading, C.Math.toRadians(state.tilted ? -42 : -89.9), range), duration: 1.0,
  });
}

/* ---------------- filtros ---------------- */
function matches(it, skip) {
  if (skip !== "t" && !state.types.has(it.t)) return false;
  if (skip !== "s" && !state.dirs.has(it.s)) return false;
  if (skip !== "ra" && !state.ras.has(it.cra)) return false;
  if (state.q) {
    const hay = it._hay || (it._hay = norm(`${it.id} ${it.end} ${it.ra}`));
    if (!state.q.split(" ").every((w) => hay.includes(w))) return false;
  }
  return true;
}
const visibleItems = () => state.items.filter((it) => matches(it));
const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function buildStaticUI() {
  // tipos
  $("typeChips").innerHTML = Object.entries(TYPES).map(([k, t]) => `
    <button type="button" class="tchip" data-t="${k}" aria-pressed="true">
      ${icoHTML(k)}
      <span><span class="t-name">${t.name}</span><span class="t-code">prefixo ${t.prefix}</span></span>
      <span class="t-n" data-n>0</span>
    </button>`).join("");
  $("typeChips").addEventListener("click", (e) => {
    const b = e.target.closest(".tchip"); if (!b) return;
    toggleSet(state.types, b.dataset.t); update();
  });

  // sentidos
  $("dirChips").innerHTML = Object.entries(DIRS).map(([k, l]) =>
    `<button type="button" class="chip" data-s="${k}" aria-pressed="true">${l}<b data-n>0</b></button>`).join("");
  $("dirChips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    toggleSet(state.dirs, b.dataset.s); update();
  });

  // RAs (ordenadas pela quantidade total)
  const ras = new Map();
  state.items.forEach((it) => ras.set(it.cra, { cra: it.cra, ra: it.ra, n: (ras.get(it.cra)?.n || 0) + 1 }));
  $("raList").innerHTML = [...ras.values()].sort((a, b) => b.n - a.n || a.cra - b.cra).map((r) => `
    <li data-cra="${r.cra}">
      <label for="ra-${r.cra}">
        <input type="checkbox" id="ra-${r.cra}" value="${r.cra}" checked>
        <span class="ra-name" title="RA ${String(r.cra).padStart(2, "0")} · ${esc(r.ra)}"><span class="code">${String(r.cra).padStart(2, "0")}</span>${esc(r.ra)}</span>
        <span class="ra-bar"><i></i></span>
        <span class="ra-n">0</span>
      </label>
    </li>`).join("");
  $("raList").addEventListener("change", (e) => {
    const v = Number(e.target.value);
    e.target.checked ? state.ras.add(v) : state.ras.delete(v); update();
  });
  $("raAll").onclick = () => { state.items.forEach((it) => state.ras.add(it.cra)); update(); };
  $("raNone").onclick = () => { state.ras.clear(); update(); };

  // busca
  let t;
  $("q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => { state.q = norm(e.target.value.trim()).replace(/\s+/g, " "); update(); }, 120);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("q").focus(); }
    if (e.key === "Escape") closeCard();
  });

  // lista
  $("results").addEventListener("click", (e) => {
    const b = e.target.closest("[data-id]");
    if (b) return select(b.dataset.id, true);
    if (e.target.closest(".more")) { state.listLimit += PAGE; renderList(); }
  });
  $("exportCsv").onclick = exportCsv;

  // barra do mapa
  $("baseSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-base]"); if (!b || !viewer || b.disabled) return;
    fallbackUsed = false; setBase(b.dataset.base);
  });
  const can3D = state.config.googleMapsKey || state.config.cesiumIonToken;
  $("btn3d").disabled = !can3D;
  $("btn3d").title = can3D
    ? (state.config.googleMapsKey ? "Prédios fotorrealistas do Google" : "Relevo e prédios (Cesium ion)")
    : "Para ativar, configure GOOGLE_MAPS_KEY ou CESIUM_ION_TOKEN no servidor (veja o README)";
  $("btn3d").onclick = () => viewer && toggle3D();
  $("btnTilt").onclick = () => viewer && toggleTilt();
  $("btnFit").onclick = () => fitVisible();
  $("btnCluster").onclick = () => {
    state.cluster = !state.cluster;
    $("btnCluster").setAttribute("aria-pressed", String(state.cluster));
    if (ds) { ds.clustering.enabled = state.cluster; viewer.scene.requestRender(); }
  };

  // ficha
  $("cardClose").onclick = closeCard;
  $("cCopy").onclick = async () => {
    const txt = $("cXY").textContent;
    try { await navigator.clipboard.writeText(txt); toast("Coordenadas copiadas."); }
    catch { const r = document.createRange(); r.selectNodeContents($("cXY")); getSelection().removeAllRanges(); getSelection().addRange(r); }
  };

  // gaveta no celular
  $("sheetToggle").onclick = () => {
    const open = $("panel").classList.toggle("open");
    $("sheetToggle").setAttribute("aria-expanded", String(open));
  };
}

function toggleSet(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

function update() {
  const vis = visibleItems(), n = vis.length;
  $("visCount").textContent = n;
  $("handleCount").textContent = n;

  // participação por tipo (barra empilhada)
  const byT = { CE: 0, RE: 0, NM: 0 };
  vis.forEach((it) => byT[it.t]++);
  $("shareBar").innerHTML = Object.keys(TYPES).filter((k) => byT[k]).map((k) =>
    `<span style="flex-grow:${byT[k]};background:${TYPE_CSS[k]}" title="${TYPES[k].name}: ${byT[k]} (${Math.round(byT[k] / n * 100)}%)"></span>`).join("");

  // contagens facetadas
  const facet = (skip, key) => { const m = {}; state.items.forEach((it) => { if (matches(it, skip)) m[it[key]] = (m[it[key]] || 0) + 1; }); return m; };
  const ft = facet("t", "t"), fs = facet("s", "s"), fr = facet("ra", "cra");
  document.querySelectorAll(".tchip").forEach((b) => {
    b.setAttribute("aria-pressed", String(state.types.has(b.dataset.t)));
    b.querySelector("[data-n]").textContent = ft[b.dataset.t] || 0;
  });
  document.querySelectorAll("#dirChips .chip").forEach((b) => {
    b.setAttribute("aria-pressed", String(state.dirs.has(b.dataset.s)));
    b.querySelector("[data-n]").textContent = fs[b.dataset.s] || 0;
  });
  const maxRa = Math.max(1, ...Object.values(fr));
  document.querySelectorAll("#raList li").forEach((li) => {
    const cra = Number(li.dataset.cra), c = fr[cra] || 0, on = state.ras.has(cra);
    li.querySelector("input").checked = on;
    li.classList.toggle("off", !on);
    li.querySelector(".ra-n").textContent = c;
    li.querySelector(".ra-bar i").style.width = (c / maxRa * 100) + "%";
    li.querySelector("label").title = `${c} equipamento(s) com os filtros atuais`;
  });

  // mapa
  if (ds) {
    const vset = new Set(vis.map((it) => it.id));
    state.items.forEach((it) => { it.entity.show = vset.has(it.id); });
    viewer.scene.requestRender();
  }
  if (state.selected && !matches(state.byId.get(state.selected))) closeCard();

  state.listLimit = PAGE;
  renderList(vis);
}

function renderList(vis = visibleItems()) {
  $("listCount").textContent = `(${vis.length})`;
  if (!vis.length) { $("results").innerHTML = `<li class="empty">Nenhum equipamento com esses filtros. Marque mais tipos, sentidos ou RAs.</li>`; return; }
  const rows = vis.slice(0, state.listLimit).map((it) => `
    <li><button type="button" data-id="${it.id}" ${it.id === state.selected ? 'aria-current="true"' : ""}>
      <span class="sw">${icoHTML(it.t)}</span>
      <span class="r-top"><span class="r-id">${it.id}</span><span class="r-ra">${esc(it.ra)}</span></span>
      <span class="r-addr">${esc(it.end)}</span>
    </button></li>`).join("");
  const more = vis.length > state.listLimit ? `<li><button type="button" class="more">Mostrar mais ${Math.min(PAGE, vis.length - state.listLimit)} de ${vis.length - state.listLimit} restantes</button></li>` : "";
  $("results").innerHTML = rows + more;
}

/* ---------------- seleção ---------------- */
function select(id, fly) {
  const it = state.byId.get(id); if (!it) return;
  if (state.selected && state.selected !== id) unmark(state.selected);
  state.selected = id;
  if (it.entity) {
    it.entity.billboard.image = state.icons[it.t].s;
    it.entity.billboard.width = it.entity.billboard.height = 40;
    it.entity.label.show = true;
    viewer.scene.requestRender();
  }
  const t = TYPES[it.t];
  $("cId").textContent = it.id;
  $("cType").innerHTML = `${icoHTML(it.t)}${t.name}`;
  $("cAddr").textContent = it.end;
  $("cRa").textContent = `${String(it.cra).padStart(2, "0")} · ${it.ra}`;
  $("cDir").textContent = DIRS[it.s];
  $("cXY").textContent = `${it.lat.toFixed(6)}, ${it.lon.toFixed(6)}`;
  $("lSv").href = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${it.lat},${it.lon}`;
  $("lGm").href = `https://www.google.com/maps/search/?api=1&query=${it.lat},${it.lon}`;
  $("lGe").href = `https://earth.google.com/web/@${it.lat},${it.lon},1100a,450d,35y,0h,60t,0r`;
  $("card").hidden = false;
  document.querySelectorAll("#results [data-id]").forEach((b) => b.dataset.id === id ? b.setAttribute("aria-current", "true") : b.removeAttribute("aria-current"));
  if (window.matchMedia("(max-width:760px)").matches) { $("panel").classList.remove("open"); $("sheetToggle").setAttribute("aria-expanded", "false"); }
  if (fly && viewer) flyToItem(it);
}

function unmark(id) {
  const it = state.byId.get(id);
  if (it && it.entity) {
    it.entity.billboard.image = state.icons[it.t].n;
    it.entity.billboard.width = it.entity.billboard.height = 28;
    it.entity.label.show = false;
  }
}

function closeCard() {
  if (state.selected) unmark(state.selected);
  state.selected = null;
  $("card").hidden = true;
  document.querySelectorAll("#results [aria-current]").forEach((b) => b.removeAttribute("aria-current"));
  if (viewer) viewer.scene.requestRender();
}

/* ---------------- exportação ---------------- */
function exportCsv() {
  const vis = visibleItems();
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const head = ["ID EQUIP", "TIPO", "COD. RA", "RA", "ENDEREÇO", "SENTIDO", "LATITUDE", "LONGITUDE"];
  const lines = [head.join(";")].concat(vis.map((it) =>
    [it.id, TYPES[it.t].name, String(it.cra).padStart(2, "0"), it.ra, it.end, DIRS[it.s], it.lat, it.lon].map(q).join(";")));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `equipamentos-df-filtrados-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast(`${vis.length} equipamentos exportados.`);
}

let toastT;
function toast(msg) {
  const el = $("toast"); el.textContent = msg; el.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => (el.hidden = true), 5000);
}
