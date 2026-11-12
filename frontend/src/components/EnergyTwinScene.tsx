import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { twinAssets, type TwinAssetId } from '../lib/twinAssets';
export interface SceneControl { view: 'overview' | 'top' | 'shore' | 'energy' | 'focus' | 'zoom-in' | 'zoom-out'; token: number; }
interface Props { selected: TwinAssetId; onSelect: (id: TwinAssetId) => void; energy: boolean; labels: boolean; animate: boolean; alerts: TwinAssetId[]; activeFlows: TwinAssetId[]; reverseFlows: TwinAssetId[]; control: SceneControl; }
export default function EnergyTwinScene(props: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const current = useRef(props); current.current = props;
  const [error, setError] = useState('');
  useEffect(() => {
    const host = mount.current!;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' }); }
    catch { setError('当前浏览器无法启用 WebGL，可通过设备清单继续查看所有数据与业务。'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.7));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.45;
    renderer.domElement.setAttribute('aria-label', '可旋转、缩放和点选设备的三维港区能源场景');
    renderer.domElement.setAttribute('role', 'img');
    host.prepend(renderer.domElement);
    const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(0x04111f, .009);
    const camera = new THREE.PerspectiveCamera(40, 1, .1, 250);
    camera.position.set(64, 63, 77);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.dampingFactor = .075; controls.minDistance = 24; controls.maxDistance = 145;
    controls.maxPolarAngle = Math.PI * .46; controls.minPolarAngle = .12; controls.target.set(0, 0, 0);
    controls.enablePan = false;
    scene.add(new THREE.AmbientLight(0xb4dfff, 2.4));
    const key = new THREE.DirectionalLight(0xb8edff, 4); key.position.set(-25, 55, 18); scene.add(key);
    const rim = new THREE.DirectionalLight(0x187eab, 2); rim.position.set(30, 15, -40); scene.add(rim);
    const material = (color: THREE.ColorRepresentation, glow = 0, opacity = 1) => new THREE.MeshStandardMaterial({ color, metalness: .55, roughness: .38, emissive: color, emissiveIntensity: glow, transparent: opacity < 1, opacity });
    const blue = material(0x245b78), dark = material(0x0b2235), cyan = material(0x42dfff, 1.3), silver = material(0x698ca1), mint = material(0x6ee7b7, .8);
    function box(parent: THREE.Object3D, x: number, y: number, z: number, w: number, h: number, d: number, mat: THREE.Material, edges = false) {
      const geometry = new THREE.BoxGeometry(w, h, d); const mesh = new THREE.Mesh(geometry, mat); mesh.position.set(x, y, z); parent.add(mesh);
      if (edges) { const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color: 0x4a9dbb, transparent: true, opacity: .6 })); mesh.add(edge); }
      return mesh;
    }
    function line(parent: THREE.Object3D, points: THREE.Vector3[], color: THREE.ColorRepresentation, opacity = 1) { const mesh = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color, transparent: true, opacity })); parent.add(mesh); return mesh; }
    box(scene, 0, -.8, 0, 72, 1.5, 53, dark, true);
    box(scene, 0, -.01, 3, 67, .05, 1.5, material(0x395269));
    box(scene, -16, -.01, -4, 1.4, .05, 44, material(0x395269));
    // Shore water and illuminated quay edge.
    box(scene, 0, -.5, 33, 110, .4, 19, material(0x063047, .18, .85));
    for (let i = 0; i < 14; i++) line(scene, [new THREE.Vector3(-52, -.25, 25 + i * 1.3), new THREE.Vector3(52, -.25, 25 + i * 1.3)], 0x27b0d0, .12);
    line(scene, [new THREE.Vector3(-36, .12, 24), new THREE.Vector3(36, .12, 24)], 0x60e7ff, .9);
    const grid = new THREE.GridHelper(150, 50, 0x17425d, 0x102a3f); grid.position.y = -1.7; scene.add(grid);
    const ring = new THREE.Mesh(new THREE.RingGeometry(45, 45.1, 128), new THREE.MeshBasicMaterial({ color: 0x1b6480, side: THREE.DoubleSide, transparent: true, opacity: .5 })); ring.rotation.x = -Math.PI / 2; ring.position.y = -1.6; scene.add(ring);
    // Use purpose-built geometry rather than claiming a surveyed plant model.
    const groups = new Map<TwinAssetId, THREE.Group>(); const halos = new Map<TwinAssetId, THREE.Mesh>();
    const selectables: THREE.Object3D[] = [];
    for (const asset of twinAssets) {
      const g = new THREE.Group(); g.position.set(...asset.position); g.userData.assetId = asset.id; scene.add(g); groups.set(asset.id, g);
      const base = box(g, 0, .03, 0, asset.id === 'shore' ? 25 : 12, .16, asset.id === 'shore' ? 8 : 10, material(asset.color, .05, .13), true); base.userData.assetId = asset.id;
      const halo = new THREE.Mesh(new THREE.RingGeometry(5.8, 6.1, 48), new THREE.MeshBasicMaterial({ color: asset.color, side: THREE.DoubleSide, transparent: true, opacity: .6 })); halo.rotation.x = -Math.PI / 2; halo.position.y = .2; g.add(halo); halos.set(asset.id, halo);
      if (asset.id === 'grid') {
        box(g, 0, 2.1, 0, 9, 4, 6, blue, true); box(g, 0, 4.2, 0, 9.4, .3, 6.5, silver);
        for (let i = -1; i <= 1; i++) { box(g, i * 2.5, 5, 0, 1.2, 1.8, 2.5, silver, true); for (let j = 0; j < 3; j++) box(g, i * 2.5, 6.3, j - 1, .2, 1, .2, cyan); }
        for (let i = 0; i < 5; i++) box(g, -4.55, 1.6, -2 + i, .1, 1.5, .13, cyan);
      } else if (asset.id === 'solar') {
        box(g, 0, 1.3, 0, 13, 2.5, 10, blue, true);
        for (let x = -2; x <= 2; x++) for (let z = -1; z <= 1; z++) { const panel = box(g, x * 2.4, 3, z * 2.9, 2.2, .18, 2.6, material(0x124c85, .4), true); panel.rotation.x = -.18; }
      } else if (asset.id === 'battery') {
        for (let i = 0; i < 4; i++) { box(g, -4.2 + i * 2.8, 1.8, 0, 2.3, 3.4, 6, blue, true); box(g, -4.2 + i * 2.8, 2, 3.04, 1.4, 2.1, .1, material(0x83f3c4, .7)); for (let j = 0; j < 3; j++) box(g, -4.2 + i * 2.8, 1 + j * .6, -3.04, 1.6, .12, .1, silver); }
      } else if (asset.id === 'reefer') {
        for (let x = -1; x <= 1; x++) for (let z = -1; z <= 1; z++) for (let y = 0; y < (z === 0 ? 3 : 2); y++) { box(g, x * 4.3, 1 + y * 1.8, z * 2.6, 4, 1.7, 2.3, material(y === 2 ? 0x527b8b : 0x206373), true); box(g, x * 4.3 + 2.02, 1 + y * 1.8, z * 2.6, .12, 1.3, 1.6, silver); }
      } else if (asset.id === 'charging') {
        for (let i = 0; i < 4; i++) { box(g, -4 + i * 2.8, .6, 0, 1.8, 1, 3.2, silver, true); box(g, -4 + i * 2.8, 1.9, -3, .7, 3.6, .6, blue); box(g, -4 + i * 2.8, 2.8, -2.66, .5, .8, .1, mint); line(g, [new THREE.Vector3(-4 + i * 2.8, 2, -2.6),new THREE.Vector3(-4 + i * 2.8, .9, -.8)],0x78ffd5); }
      } else if (asset.id === 'building') {
        box(g, 0, 4, 0, 9, 8, 6, blue, true); box(g, 0, 8.2, 0, 9.7, .3, 6.7, silver);
        for (let y = 1; y < 8; y += 1.6) for (let x = -3; x <= 3; x += 2) box(g, x, y, 3.03, 1.2, .65, .1, material(0x70dcf8, .8));
        box(g, 0, 9, 0, 3, 1.4, 2, silver);
      } else {
        for (let i = 0; i < 3; i++) {
          const x = -8 + i * 8; box(g, x, 2, 2, 1.8, 4, 2, blue, true); box(g, x, 4.2, 2, 2.5, .35, 2.6, cyan);
          for (const dx of [-1.7, 1.7]) box(g, x + dx, 3.8, 0, .35, 7, .35, silver);
          box(g, x, 7.1, 2, 4.3, .45, 13, silver, true); line(g, [new THREE.Vector3(x, 7, 7),new THREE.Vector3(x, 3, 7)],0x77e9ff);
        }
      }
      g.traverse((o) => { if (o instanceof THREE.Mesh) { o.userData.assetId = asset.id; selectables.push(o); } });
    }
    // Docked vessel, cranes and container yard enrich the spatial context.
    const vessel = new THREE.Group(); vessel.position.set(11, 0, 29); scene.add(vessel);
    const hull = new THREE.Mesh(new THREE.CapsuleGeometry(2.5, 22, 4, 12), material(0x17506f)); hull.rotation.z = Math.PI / 2; hull.scale.z = .65; hull.position.y = .5; vessel.add(hull);
    box(vessel, 0, 1.4, 0, 22, .4, 4.7, silver);
    for (let i = -3; i <= 3; i++) for (let j = -1; j <= 1; j++) box(vessel, i * 2.4, 2, j * 1.4, 2.2, 1.1, 1.2, material(i % 2 ? 0x2a8598 : 0x326076), true);
    box(vessel, -9, 3.3, 0, 2.3, 3.4, 3.9, blue, true);
    const flows = new Map<TwinAssetId, { group: THREE.Group; curve: THREE.CatmullRomCurve3; particles: THREE.Mesh[] }>();
    const hub = new THREE.Vector3(-16, .6, -2);
    for (const asset of twinAssets) {
      const group = new THREE.Group(); scene.add(group);
      const target = new THREE.Vector3(asset.position[0], .7, asset.position[2]);
      const curve = new THREE.CatmullRomCurve3([hub, new THREE.Vector3(hub.x, 1, target.z), target]);
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 36, .065, 5, false), new THREE.MeshBasicMaterial({ color: asset.color, transparent: true, opacity: .6 })); group.add(tube);
      const particles: THREE.Mesh[] = [];
      for (let j = 0; j < 4; j++) { const p = new THREE.Mesh(new THREE.SphereGeometry(.26, 6, 6), new THREE.MeshBasicMaterial({ color: asset.color })); group.add(p); particles.push(p); }
      flows.set(asset.id, { group, curve, particles });
    }
    // Labels follow their 3D anchors and remain native, keyboard-operable buttons.
    const labelLayer = host.querySelector('.twin-scene-labels')!;
    let start = { x: 0, y: 0 }; const raycaster = new THREE.Raycaster();
    const down = (event: PointerEvent) => { start = { x: event.clientX, y: event.clientY }; };
    const click = (event: PointerEvent) => {
      if (Math.hypot(start.x - event.clientX, start.y - event.clientY) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
      const hit = raycaster.intersectObjects(selectables, false)[0];
      if (hit?.object.userData.assetId) current.current.onSelect(hit.object.userData.assetId as TwinAssetId);
    };
    renderer.domElement.addEventListener('pointerdown', down); renderer.domElement.addEventListener('pointerup', click);
    const resize = new ResizeObserver(() => { const w = host.clientWidth, h = host.clientHeight; if (!w || !h) return; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }); resize.observe(host);
    let frame = 0, previous = -1, previousSelected = '', lastDraw = 0, active = true;
    const animate = (time: number) => {
      frame = requestAnimationFrame(animate);
      if (!active || document.hidden || time - lastDraw < 32) return; lastDraw = time;
      const state = current.current;
      if (previous !== state.control.token) {
        previous = state.control.token; const view = state.control.view;
        if (view === 'zoom-in' || view === 'zoom-out') { const delta = camera.position.clone().sub(controls.target).multiplyScalar(view === 'zoom-in' ? .8 : 1.2); delta.clampLength(24, 145); camera.position.copy(controls.target).add(delta); }
        else {
          const positions = { overview: [64, 63, 77], top: [0, 105, 1], shore: [46, 32, 65], energy: [-57, 43, 40], focus: [0, 0, 0] };
          const position = positions[view];
          if (view === 'focus') { const a = twinAssets.find((item) => item.id === state.selected)!; controls.target.set(...a.position); camera.position.set(a.position[0] + 20, 24, a.position[2] + 24); }
          else { controls.target.set(0, 0, view === 'shore' ? 8 : 0); camera.position.set(...position as [number, number, number]); }
        }
      }
      if (previousSelected !== state.selected) { previousSelected = state.selected; host.setAttribute('data-selected', state.selected); }
      for (const asset of twinAssets) {
        const halo = halos.get(asset.id)!;
        const alert = state.alerts.includes(asset.id), selected = state.selected === asset.id;
        (halo.material as THREE.MeshBasicMaterial).color.set(alert ? '#ffb75e' : asset.color);
        (halo.material as THREE.MeshBasicMaterial).opacity = selected ? .95 : alert ? .8 : .18;
        const s = selected && state.animate ? 1 + Math.sin(time * .0016) * .035 : 1; halo.scale.setScalar(s);
        const flow = flows.get(asset.id)!; flow.group.visible = state.energy && state.activeFlows.includes(asset.id);
        flow.particles.forEach((p, i) => { p.visible = state.animate; p.position.copy(flow.curve.getPointAt(state.reverseFlows.includes(asset.id) ? 1 - (time * .00009 + i / 4) % 1 : (time * .00009 + i / 4) % 1)); });
        const label = labelLayer.querySelector<HTMLElement>(`[data-asset-label="${asset.id}"]`)!;
        const projection = new THREE.Vector3(asset.position[0], asset.id === 'building' ? 11 : asset.id === 'shore' ? 9 : 7, asset.position[2]).project(camera);
        label.style.left = `${(projection.x * .5 + .5) * host.clientWidth}px`; label.style.top = `${(-projection.y * .5 + .5) * host.clientHeight}px`;
        label.hidden = !state.labels || projection.z > 1 || Math.abs(projection.x) > .94 || Math.abs(projection.y) > .92;
      }
      const occupied: DOMRect[] = [];
      const ordered = [...twinAssets].sort((a, b) => a.id === state.selected ? -1 : b.id === state.selected ? 1 : 0);
      for (const asset of ordered) {
        const label = labelLayer.querySelector<HTMLElement>(`[data-asset-label="${asset.id}"]`)!;
        label.style.visibility = 'visible';
        if (label.hidden) continue;
        const rect = label.getBoundingClientRect();
        if (occupied.some((r) => rect.left < r.right + 4 && rect.right > r.left - 4 && rect.top < r.bottom + 4 && rect.bottom > r.top - 4)) label.style.visibility = 'hidden';
        else occupied.push(rect);
      }
      controls.update(); renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(animate);
    const lost = (event: Event) => { event.preventDefault(); active = false; setError('三维绘制已中断。设备数据仍可查看，请点击“重新载入场景”恢复。'); };
    renderer.domElement.addEventListener('webglcontextlost', lost);
    return () => {
      cancelAnimationFrame(frame); resize.disconnect(); controls.dispose();
      renderer.domElement.removeEventListener('pointerdown', down); renderer.domElement.removeEventListener('pointerup', click); renderer.domElement.removeEventListener('webglcontextlost', lost);
      const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
      scene.traverse((o) => { if (o instanceof THREE.Mesh || o instanceof THREE.Line) { geometries.add(o.geometry); const mats = Array.isArray(o.material) ? o.material : [o.material]; mats.forEach((mat) => materials.add(mat)); } });
      geometries.forEach((g) => g.dispose()); materials.forEach((m) => m.dispose()); renderer.dispose(); renderer.domElement.remove();
    };
  }, []);
  return <div className="twin-scene-canvas" ref={mount} data-renderer={error ? 'unavailable' : 'webgl'}>
    <div className="twin-scene-labels">{twinAssets.map((asset) => <button data-asset-label={asset.id} key={asset.id} className={props.selected === asset.id ? 'selected' : ''} type="button" onClick={() => props.onSelect(asset.id)} aria-label={`选择${asset.name}`}><i style={{ background: props.alerts.includes(asset.id) ? '#ffb75e' : asset.color }}/><b>{asset.name}</b><small>{asset.code}</small></button>)}</div>
    {error && <div className="twin-webgl-error" role="alert">{error}</div>}
  </div>;
}
