import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// Backbone tube through the C-alpha atoms, coloured by AlphaFold confidence (pLDDT):
// gold where the model is confident, pale blue where it is not.
const HIGH = new THREE.Color("#fdb515");
const MID = new THREE.Color("#7fa6e8");
const LOW = new THREE.Color("#c9d4ef");

function confidenceColour(plddt) {
  if (plddt >= 90) return HIGH;
  if (plddt >= 70) return HIGH.clone().lerp(MID, (90 - plddt) / 20);
  return MID.clone().lerp(LOW, Math.min(1, (70 - plddt) / 20));
}

export default function Protein3D({ trace }) {
  const mount = useRef(null);

  useEffect(() => {
    const el = mount.current;
    if (!el || !trace?.length) return undefined;
    const width = el.clientWidth, height = el.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, width / height, 1, 2000);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    el.appendChild(renderer.domElement);

    // Centre the protein on the origin so it turns about its own middle.
    const points = trace.map(([x, y, z]) => new THREE.Vector3(x, y, z));
    const centre = points.reduce((sum, p) => sum.add(p), new THREE.Vector3()).divideScalar(points.length);
    points.forEach((p) => p.sub(centre));
    const radius = Math.max(...points.map((p) => p.length()));

    const curve = new THREE.CatmullRomCurve3(points);
    const tubular = Math.min(points.length * 4, 4000), radial = 8;
    const geometry = new THREE.TubeGeometry(curve, tubular, 0.9, radial, false);
    const colours = new Float32Array(geometry.attributes.position.count * 3);
    for (let i = 0; i <= tubular; i++) {
      const residue = Math.min(trace.length - 1, Math.round((i / tubular) * (trace.length - 1)));
      const c = confidenceColour(trace[residue][3]);
      for (let j = 0; j <= radial; j++) c.toArray(colours, (i * (radial + 1) + j) * 3);
    }
    geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
    const tube = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.35, metalness: 0.15 }));
    scene.add(tube);

    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 1.2, 1.5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x7fa6e8, 0.8);
    rim.position.set(-1.5, -0.5, -1);
    scene.add(rim);

    camera.position.set(0, 0, radius * 2.6);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.autoRotate = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    controls.autoRotateSpeed = 1.6;

    let frame = 0;
    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    tick();

    const onResize = () => {
      const w = el.clientWidth, h = el.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      controls.dispose();
      geometry.dispose();
      tube.material.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [trace]);

  return <div className="protein3d" ref={mount} data-testid="protein3d" role="img" aria-label="Rotating 3D backbone of the protein" />;
}
