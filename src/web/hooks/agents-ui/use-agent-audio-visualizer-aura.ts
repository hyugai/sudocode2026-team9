/** LiveKit Agents UI. Modified locally: animation cleanup and reduced motion. See NOTICE.md. */
import { useEffect, useRef, useState, useCallback } from 'react';
import { type LocalAudioTrack, type RemoteAudioTrack } from 'livekit-client';
import {
  type AnimationPlaybackControlsWithThen,
  type ValueAnimationTransition,
  animate,
  useMotionValue,
  useMotionValueEvent,
} from 'motion/react';
import {
  type AgentState,
  type TrackReference,
  type TrackReferenceOrPlaceholder,
  useTrackVolume,
} from '@livekit/components-react';

const DEFAULT_SPEED = 10;
const DEFAULT_AMPLITUDE = 2;
const DEFAULT_FREQUENCY = 0.5;
const DEFAULT_SCALE = 0.2;
const DEFAULT_BRIGHTNESS = 1.5;
const DEFAULT_TRANSITION: ValueAnimationTransition = { duration: 0.5, ease: 'easeOut' };
const DEFAULT_PULSE_TRANSITION: ValueAnimationTransition = {
  duration: 0.35,
  ease: 'easeOut',
  repeat: Infinity,
  repeatType: 'mirror',
};

function useAnimatedValue<T>(initialValue: T, animationsEnabled: boolean) {
  const [value, setValue] = useState(initialValue);
  const motionValue = useMotionValue(initialValue);
  const controlsRef = useRef<AnimationPlaybackControlsWithThen | null>(null);
  useMotionValueEvent(motionValue, 'change', (value) => setValue(value as T));

  const animateFn = useCallback(
    (targetValue: T | T[], transition: ValueAnimationTransition) => {
      controlsRef.current?.stop();
      controlsRef.current = animate(motionValue, targetValue, transition);
    },
    [motionValue],
  );

  useEffect(() => {
    if (!animationsEnabled) controlsRef.current?.stop();
    return () => controlsRef.current?.stop();
  }, [animationsEnabled]);

  return { value, motionValue, controls: controlsRef, animate: animateFn };
}

export function useAgentAudioVisualizerAura(
  state: AgentState | undefined,
  audioTrack?: LocalAudioTrack | RemoteAudioTrack | TrackReferenceOrPlaceholder,
  volumeProp?: number,
  animationsEnabled = true,
) {
  const speed = state === 'speaking' ? 70
    : state === 'thinking' || state === 'connecting' || state === 'initializing' ? 30
    : state === 'listening' || state === 'pre-connect-buffering' ? 20 : DEFAULT_SPEED;
  const {
    value: scale,
    animate: animateScale,
    motionValue: scaleMotionValue,
  } = useAnimatedValue(DEFAULT_SCALE, animationsEnabled);
  const { value: amplitude, animate: animateAmplitude } = useAnimatedValue(DEFAULT_AMPLITUDE, animationsEnabled);
  const { value: frequency, animate: animateFrequency } = useAnimatedValue(DEFAULT_FREQUENCY, animationsEnabled);
  const { value: brightness, animate: animateBrightness } = useAnimatedValue(DEFAULT_BRIGHTNESS, animationsEnabled);

  const trackVolume = useTrackVolume(audioTrack as TrackReference, {
    fftSize: 512,
    smoothingTimeConstant: 0.55,
  });
  const rawVolume = volumeProp ?? trackVolume;
  const volume = Number.isFinite(rawVolume) ? Math.max(0, Math.min(1, rawVolume)) : 0;

  useEffect(() => {
    if (!animationsEnabled) return;
    switch (state) {
      case 'idle':
      case 'failed':
      case 'disconnected':
        animateScale(0.2, DEFAULT_TRANSITION);
        animateAmplitude(1.2, DEFAULT_TRANSITION);
        animateFrequency(0.4, DEFAULT_TRANSITION);
        animateBrightness(1.0, DEFAULT_TRANSITION);
        return;
      case 'listening':
      case 'pre-connect-buffering':
        animateScale(0.3, { type: 'spring', duration: 1.0, bounce: 0.35 });
        animateAmplitude(1.0, DEFAULT_TRANSITION);
        animateFrequency(0.7, DEFAULT_TRANSITION);
        animateBrightness([1.5, 2.0], DEFAULT_PULSE_TRANSITION);
        return;
      case 'thinking':
      case 'connecting':
      case 'initializing':
        animateScale(0.3, DEFAULT_TRANSITION);
        animateAmplitude(0.5, DEFAULT_TRANSITION);
        animateFrequency(1, DEFAULT_TRANSITION);
        animateBrightness([0.5, 2.5], DEFAULT_PULSE_TRANSITION);
        return;
      case 'speaking':
        animateScale(0.3, DEFAULT_TRANSITION);
        animateAmplitude(0.75, DEFAULT_TRANSITION);
        animateFrequency(1.25, DEFAULT_TRANSITION);
        animateBrightness(1.5, DEFAULT_TRANSITION);
        return;
    }
  }, [state, animationsEnabled, animateScale, animateAmplitude, animateFrequency, animateBrightness]);

  useEffect(() => {
    if (animationsEnabled && state === 'speaking' && !scaleMotionValue.isAnimating()) {
      animateScale(0.2 + 0.2 * volume, { duration: 0 });
    }
  }, [
    state,
    animationsEnabled,
    volume,
    scaleMotionValue,
    animateScale,
    animateAmplitude,
    animateFrequency,
    animateBrightness,
  ]);

  return {
    speed,
    scale,
    amplitude,
    frequency,
    brightness,
  };
}
