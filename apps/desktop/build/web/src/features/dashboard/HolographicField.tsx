import { useEffect, useRef } from "react";
import * as THREE from "three";

type Props = {
  active?: boolean;
};

const vertexShader = `
  varying vec3 vNormal;
  varying vec3 vPosition;

  void main() {
    vNormal = normalize(normalMatrix * normal);
    vPosition = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const fragmentShader = `
  uniform float uTime;
  uniform float uActive;
  varying vec3 vNormal;
  varying vec3 vPosition;

  void main() {
    float fresnel = pow(1.0 - abs(vNormal.z), 2.2);
    float scan = 0.55 + 0.45 * sin((vPosition.y * 19.0) - (uTime * 4.2));
    float pulse = 0.78 + 0.22 * sin((uTime * 2.0) + (vPosition.x * 4.0));
    float alpha = (0.11 + fresnel * 0.52) * scan * pulse;
    alpha *= mix(0.72, 1.18, uActive);

    vec3 cyan = vec3(0.18, 0.86, 1.0);
    vec3 teal = vec3(0.20, 1.0, 0.72);
    vec3 color = mix(cyan, teal, fresnel * 0.55 + uActive * 0.18);

    gl_FragColor = vec4(color, alpha);
  }
`;

function disposeObject(root: THREE.Object3D) {
  root.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (mesh.geometry) {
      mesh.geometry.dispose();
    }

    const material = mesh.material;
    if (Array.isArray(material)) {
      material.forEach((entry) => entry.dispose());
    } else if (material) {
      material.dispose();
    }
  });
}

export default function HolographicField({
  active = false,
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef(active);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      42,
      1,
      0.1,
      100,
    );
    camera.position.set(0, 0.1, 7.5);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch {
      return;
    }

    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio || 1, 1.6),
    );
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const root = new THREE.Group();
    root.position.set(2.55, -0.2, 0);
    root.rotation.set(-0.12, 0.08, 0.08);
    scene.add(root);

    const hologramMaterial = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      uniforms: {
        uTime: { value: 0 },
        uActive: { value: activeRef.current ? 1 : 0 },
      },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });

    const shell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.52, 3),
      hologramMaterial,
    );
    root.add(shell);

    const innerShell = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.08, 2),
      new THREE.MeshBasicMaterial({
        color: 0x53f4ff,
        wireframe: true,
        transparent: true,
        opacity: 0.07,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    root.add(innerShell);

    const ringMaterial = new THREE.MeshBasicMaterial({
      color: 0x63e6ff,
      transparent: true,
      opacity: 0.18,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const ringA = new THREE.Mesh(
      new THREE.TorusGeometry(2.08, 0.012, 8, 180),
      ringMaterial,
    );
    ringA.rotation.x = Math.PI / 2.9;
    ringA.rotation.y = 0.25;
    root.add(ringA);

    const ringB = new THREE.Mesh(
      new THREE.TorusGeometry(1.88, 0.009, 8, 180),
      ringMaterial.clone(),
    );
    ringB.rotation.x = Math.PI / 1.8;
    ringB.rotation.z = 0.75;
    root.add(ringB);

    const ringC = new THREE.Mesh(
      new THREE.TorusGeometry(2.35, 0.006, 8, 180),
      ringMaterial.clone(),
    );
    ringC.rotation.y = Math.PI / 2.4;
    ringC.rotation.z = -0.3;
    root.add(ringC);

    const particleCount = 460;
    const particlePositions = new Float32Array(
      particleCount * 3,
    );

    for (let index = 0; index < particleCount; index += 1) {
      const radius =
        2.2 + Math.random() * 3.8;
      const theta = Math.random() * Math.PI * 2;
      const phi =
        Math.acos(2 * Math.random() - 1);

      particlePositions[index * 3] =
        radius * Math.sin(phi) * Math.cos(theta);
      particlePositions[index * 3 + 1] =
        radius * Math.cos(phi);
      particlePositions[index * 3 + 2] =
        radius * Math.sin(phi) * Math.sin(theta);
    }

    const particleGeometry =
      new THREE.BufferGeometry();
    particleGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(
        particlePositions,
        3,
      ),
    );

    const particles = new THREE.Points(
      particleGeometry,
      new THREE.PointsMaterial({
        color: 0x63e6ff,
        size: 0.018,
        transparent: true,
        opacity: 0.24,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        sizeAttenuation: true,
      }),
    );
    root.add(particles);

    const glow = new THREE.Mesh(
      new THREE.SphereGeometry(1.65, 48, 48),
      new THREE.MeshBasicMaterial({
        color: 0x126b85,
        transparent: true,
        opacity: 0.045,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    root.add(glow);

    const clock = new THREE.Clock();
    let frame = 0;
    let visible = !document.hidden;

    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();

      const compact = width < 920;
      root.position.x = compact ? 0.9 : 2.55;
      root.position.y = compact ? -1.05 : -0.2;
      root.scale.setScalar(compact ? 0.72 : 1);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();

    const renderFrame = () => {
      if (!visible) return;

      const elapsed = clock.getElapsedTime();
      const targetActive = activeRef.current ? 1 : 0;
      hologramMaterial.uniforms.uTime.value =
        elapsed;
      hologramMaterial.uniforms.uActive.value =
        THREE.MathUtils.lerp(
          hologramMaterial.uniforms.uActive.value,
          targetActive,
          0.045,
        );

      if (!reducedMotion) {
        const speed = activeRef.current ? 1.45 : 0.72;
        root.rotation.y += 0.0018 * speed;
        shell.rotation.x =
          Math.sin(elapsed * 0.28) * 0.11;
        shell.rotation.z =
          Math.cos(elapsed * 0.23) * 0.09;
        innerShell.rotation.y -= 0.0022 * speed;
        ringA.rotation.z += 0.0024 * speed;
        ringB.rotation.y -= 0.0017 * speed;
        ringC.rotation.x += 0.0012 * speed;
        particles.rotation.y += 0.00035 * speed;

        const pulse =
          1 +
          Math.sin(elapsed * (activeRef.current ? 3.4 : 1.4)) *
            (activeRef.current ? 0.022 : 0.008);
        glow.scale.setScalar(pulse);
      }

      renderer.render(scene, camera);
      frame = window.requestAnimationFrame(renderFrame);
    };

    const onVisibility = () => {
      visible = !document.hidden;
      if (visible) {
        clock.getDelta();
        window.cancelAnimationFrame(frame);
        frame = window.requestAnimationFrame(renderFrame);
      } else {
        window.cancelAnimationFrame(frame);
      }
    };

    document.addEventListener(
      "visibilitychange",
      onVisibility,
    );

    if (reducedMotion) {
      hologramMaterial.uniforms.uTime.value = 0.4;
      renderer.render(scene, camera);
    } else {
      frame = window.requestAnimationFrame(renderFrame);
    }

    return () => {
      document.removeEventListener(
        "visibilitychange",
        onVisibility,
      );
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      disposeObject(root);
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className={
        active
          ? "holographicField active"
          : "holographicField"
      }
      aria-hidden="true"
    />
  );
}
