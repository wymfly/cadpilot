import { useState, useRef, useCallback, useEffect, Suspense, forwardRef, useImperativeHandle } from 'react';
import { Canvas, useThree, useLoader } from '@react-three/fiber';
import { OrbitControls, Center, Environment } from '@react-three/drei';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import * as THREE from 'three';
import { Spin } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import TerminalCursor from '../decorative/TerminalCursor.tsx';
import { createDfamMaterial, type DfamMeshMeta } from './DfamShader.ts';
import HeatmapLegend from './HeatmapLegend.tsx';
import ViewControls from './ViewControls.tsx';
import type { DfamMode } from './ViewControls.tsx';

export interface Viewer3DHandle {
  focusOnRegion: (region: { center: number[]; radius: number }) => void;
}

interface Viewer3DProps {
  modelUrl: string | null;
  dfamGlbUrl?: string | null;
  wireframe?: boolean;
  darkMode?: boolean;
  previewLoading?: boolean;
  previewError?: string | null;
  previewTimedOut?: boolean;
  onRetryPreview?: () => void;
  onLoaded?: () => void;
}

interface ModelProps {
  url: string;
  wireframe: boolean;
  visible?: boolean;
  onLoaded?: () => void;
  onBoundsReady?: (radius: number) => void;
}

function Model({ url, wireframe, visible = true, onLoaded, onBoundsReady }: ModelProps) {
  const gltf = useLoader(GLTFLoader, url);

  // Apply wireframe to all meshes
  gltf.scene.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      if (Array.isArray(child.material)) {
        child.material.forEach((mat) => {
          mat.wireframe = wireframe;
        });
      } else {
        child.material.wireframe = wireframe;
      }
    }
  });

  gltf.scene.visible = visible;

  useEffect(() => {
    if (onLoaded) onLoaded();
    if (onBoundsReady) {
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const sphere = new THREE.Sphere();
      box.getBoundingSphere(sphere);
      onBoundsReady(sphere.radius);
    }
  }, [url, onLoaded, onBoundsReady, gltf.scene]);

  return (
    <Center>
      <primitive object={gltf.scene} />
    </Center>
  );
}

/** Renders the DfAM heatmap scene loaded externally. */
function DfamOverlay({ group }: { group: THREE.Group }) {
  return (
    <Center>
      <primitive object={group} />
    </Center>
  );
}

interface CameraControllerProps {
  targetPosition: [number, number, number] | null;
  focusRegion: { center: number[]; radius: number } | null;
  orbitRef: React.RefObject<any>;
  onAnimationDone: () => void;
}

function CameraController({ targetPosition, focusRegion, orbitRef, onAnimationDone }: CameraControllerProps) {
  const { camera } = useThree();

  useEffect(() => {
    if (focusRegion) {
      const center = new THREE.Vector3(...focusRegion.center);
      const viewDistance = Math.max(focusRegion.radius * 3, 2);
      const direction = camera.position.clone().sub(new THREE.Vector3(0, 0, 0)).normalize();
      camera.position.copy(center.clone().add(direction.multiplyScalar(viewDistance)));
      camera.lookAt(center);
      // Sync OrbitControls target so it orbits around the focused region
      if (orbitRef.current) {
        orbitRef.current.target.copy(center);
        orbitRef.current.update();
      }
      onAnimationDone();
    } else if (targetPosition) {
      const currentDistance = camera.position.length();
      const targetVec = new THREE.Vector3(...targetPosition).normalize().multiplyScalar(currentDistance);
      camera.position.copy(targetVec);
      camera.lookAt(0, 0, 0);
      if (orbitRef.current) {
        orbitRef.current.target.set(0, 0, 0);
        orbitRef.current.update();
      }
      onAnimationDone();
    }
  }, [camera, focusRegion, targetPosition, orbitRef, onAnimationDone]);

  return null;
}

/** Auto-frame camera to fit the loaded model's bounding sphere. */
function AutoFramer({ radius, orbitRef }: { radius: number; orbitRef: React.RefObject<any> }) {
  const { camera } = useThree();

  useEffect(() => {
    if (radius <= 0) return;

    const cam = camera as THREE.PerspectiveCamera;
    const fov = cam.fov * (Math.PI / 180);
    const distance = (radius / Math.sin(fov / 2)) * 1.2;

    const dir = new THREE.Vector3(1, 0.8, 1).normalize();
    cam.position.copy(dir.multiplyScalar(distance));
    cam.lookAt(0, 0, 0);
    cam.near = Math.max(distance * 0.01, 0.01);
    cam.far = distance * 10;
    cam.updateProjectionMatrix();

    if (orbitRef.current) {
      orbitRef.current.target.set(0, 0, 0);
      orbitRef.current.minDistance = radius * 0.1;
      orbitRef.current.maxDistance = distance * 3;
      orbitRef.current.update();
    }
  }, [radius, camera, orbitRef]);

  return null;
}

const Viewer3D = forwardRef<Viewer3DHandle, Viewer3DProps>(function Viewer3D({
  modelUrl,
  dfamGlbUrl,
  wireframe: externalWireframe,
  darkMode = false,
  previewLoading = false,
  previewError,
  previewTimedOut = false,
  onRetryPreview,
  onLoaded,
}, ref) {
  const [internalWireframe, setInternalWireframe] = useState(false);
  const [cameraTarget, setCameraTarget] = useState<[number, number, number] | null>(null);
  const [focusRegion, setFocusRegion] = useState<{ center: number[]; radius: number } | null>(null);
  const [modelRadius, setModelRadius] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const orbitRef = useRef<any>(null);

  const handleBoundsReady = useCallback((radius: number) => {
    setModelRadius(radius);
  }, []);

  // DfAM state
  const [dfamMode, setDfamMode] = useState<DfamMode>('normal');
  const [dfamScene, setDfamScene] = useState<THREE.Group | null>(null);
  const [dfamMeta, setDfamMeta] = useState<DfamMeshMeta | null>(null);
  const [dfamLoading, setDfamLoading] = useState(false);
  const [loadedDfamUrl, setLoadedDfamUrl] = useState<string | null>(null);

  const wireframe = externalWireframe ?? internalWireframe;

  useImperativeHandle(ref, () => ({
    focusOnRegion(region: { center: number[]; radius: number }) {
      setFocusRegion(region);
    },
  }), []);

  const handleViewChange = useCallback((position: [number, number, number]) => {
    setCameraTarget(position);
  }, []);

  const handleAnimationDone = useCallback(() => {
    setCameraTarget(null);
    setFocusRegion(null);
  }, []);

  // Reset model radius when URL changes (triggers re-frame on new model)
  useEffect(() => {
    setModelRadius(0);
  }, [modelUrl]);

  // Reset cached DfAM scene when URL changes (new job)
  useEffect(() => {
    if (dfamGlbUrl !== loadedDfamUrl) {
      setDfamScene(null);
      setDfamMeta(null);
      setLoadedDfamUrl(null);
    }
  }, [dfamGlbUrl, loadedDfamUrl]);

  // Load DfAM GLB when switching away from 'normal'
  useEffect(() => {
    if (dfamMode === 'normal' || !dfamGlbUrl || dfamLoading) return;
    if (dfamScene && loadedDfamUrl === dfamGlbUrl) return;

    setDfamLoading(true);
    const loader = new GLTFLoader();
    loader.load(
      dfamGlbUrl,
      (gltf) => {
        const group = gltf.scene;

        // Apply DfAM shader to all meshes and extract metadata
        group.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.material = createDfamMaterial();
          }
        });

        setDfamScene(group);
        setLoadedDfamUrl(dfamGlbUrl);
        setDfamLoading(false);
      },
      undefined,
      () => {
        setDfamLoading(false);
      },
    );
  }, [dfamMode, dfamScene, dfamGlbUrl, dfamLoading, loadedDfamUrl]);

  // Toggle mesh visibility based on dfamMode
  useEffect(() => {
    if (!dfamScene) return;

    dfamScene.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        const meshType = child.name; // "wall_thickness" or "overhang"
        if (dfamMode === 'normal') {
          child.visible = false;
        } else {
          child.visible = meshType === dfamMode;
        }

        // Update meta for active mesh
        if (child.visible && child.userData?.analysis_type) {
          setDfamMeta({
            analysis_type: child.userData.analysis_type,
            threshold: child.userData.threshold ?? 0,
            min_value: child.userData.min_value ?? null,
            max_value: child.userData.max_value ?? null,
            vertices_at_risk_count: child.userData.vertices_at_risk_count ?? 0,
            vertices_at_risk_percent: child.userData.vertices_at_risk_percent ?? 0,
          });
        }
      }
    });

    if (dfamMode === 'normal') {
      setDfamMeta(null);
    }
  }, [dfamMode, dfamScene]);

  const showOriginalModel = dfamMode === 'normal';
  const dfamAvailable = !!dfamGlbUrl;

  const dt = useDesignTokens();
  const bgColor = dt.color.surface0;
  const ambientIntensity = dt.isDark ? 0.3 : 0.5;
  const gridColors: [string, string] = dt.isDark ? ['#333', '#222'] : ['#ccc', '#eee'];
  const placeholderColor = dt.color.surface3;

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        minHeight: 400,
        position: 'relative',
        background: bgColor,
        borderRadius: dt.radius.md,
        overflow: 'hidden',
      }}
    >
      <Canvas
        camera={{ position: [3, 3, 3], fov: 45, near: 0.1, far: 1000 }}
        style={{ width: '100%', height: '100%' }}
      >
        <color attach="background" args={[bgColor]} />
        <ambientLight intensity={ambientIntensity} />
        <directionalLight position={[5, 5, 5]} intensity={darkMode ? 0.8 : 1} />
        <directionalLight position={[-3, -3, -3]} intensity={darkMode ? 0.2 : 0.3} />
        <Environment preset="studio" />
        <OrbitControls
          ref={orbitRef}
          enableDamping
          dampingFactor={0.1}
        />
        <CameraController
          targetPosition={cameraTarget}
          focusRegion={focusRegion}
          orbitRef={orbitRef}
          onAnimationDone={handleAnimationDone}
        />
        {modelRadius > 0 && (
          <AutoFramer radius={modelRadius} orbitRef={orbitRef} />
        )}
        {modelUrl && (
          <Suspense fallback={null}>
            <Model url={modelUrl} wireframe={wireframe} visible={showOriginalModel} onLoaded={onLoaded} onBoundsReady={handleBoundsReady} />
          </Suspense>
        )}
        {dfamScene && dfamMode !== 'normal' && (
          <DfamOverlay group={dfamScene} />
        )}
        {!modelUrl && (
          <mesh>
            <boxGeometry args={[1, 1, 1]} />
            <meshStandardMaterial color={placeholderColor} wireframe={wireframe} />
          </mesh>
        )}
        <gridHelper key={`${darkMode}-${modelRadius}`} args={[modelRadius > 0 ? Math.ceil(modelRadius * 4 / 10) * 10 : 10, 10, gridColors[0], gridColors[1]]} />
      </Canvas>

      {!modelUrl && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            pointerEvents: 'none',
          }}
        >
          <TerminalCursor message="Awaiting model..." />
        </div>
      )}

      <ViewControls
        wireframe={wireframe}
        dfamMode={dfamMode}
        dfamAvailable={dfamAvailable}
        onWireframeToggle={() => setInternalWireframe((v) => !v)}
        onViewChange={handleViewChange}
        onDfamModeChange={setDfamMode}
      />

      {/* DfAM heatmap legend */}
      {dfamMode !== 'normal' && dfamMeta && (
        <HeatmapLegend
          type={dfamMeta.analysis_type}
          min={dfamMeta.min_value}
          max={dfamMeta.max_value}
          threshold={dfamMeta.threshold}
          verticesAtRisk={dfamMeta.vertices_at_risk_count}
          verticesAtRiskPercent={dfamMeta.vertices_at_risk_percent}
        />
      )}

      {/* DfAM loading indicator */}
      {dfamLoading && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            background: dt.color.glassBg,
            backdropFilter: 'blur(12px)',
            borderRadius: dt.radius.sm,
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12,
            fontFamily: dt.typography.fontMono,
            color: dt.color.textSecondary,
            boxShadow: dt.shadow.panel,
          }}
        >
          <Spin size="small" />
          加载热力图...
        </div>
      )}

      {/* Preview loading overlay */}
      {previewLoading && modelUrl && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            background: dt.color.glassBg,
            backdropFilter: 'blur(12px)',
            borderRadius: dt.radius.sm,
            padding: '6px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 12,
            fontFamily: dt.typography.fontMono,
            color: dt.color.textSecondary,
            boxShadow: dt.shadow.panel,
          }}
        >
          <Spin size="small" />
          预览更新中...
        </div>
      )}

      {/* Timeout / error overlay */}
      {(previewTimedOut || previewError) && !previewLoading && (
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            background: dt.color.glassBg,
            backdropFilter: 'blur(12px)',
            borderRadius: dt.radius.sm,
            padding: '8px 12px',
            fontSize: 12,
            fontFamily: dt.typography.fontMono,
            color: previewTimedOut ? dt.color.warning : dt.color.error,
            boxShadow: dt.shadow.panel,
            maxWidth: 200,
          }}
        >
          <div>{previewTimedOut ? '预览超时' : '预览不可用'}</div>
          {previewError && (
            <div style={{ fontSize: 11, marginTop: 2, opacity: 0.8 }}>
              {previewError}
            </div>
          )}
          {onRetryPreview && (
            <button
              onClick={onRetryPreview}
              style={{
                marginTop: 4,
                padding: '2px 8px',
                fontSize: 11,
                border: '1px solid currentColor',
                borderRadius: 4,
                background: 'transparent',
                color: 'inherit',
                cursor: 'pointer',
              }}
            >
              重试
            </button>
          )}
        </div>
      )}
    </div>
  );
});

export default Viewer3D;
