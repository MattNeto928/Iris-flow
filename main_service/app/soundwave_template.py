# Template for Manim Audio Visualization
SOUNDWAVE_TEMPLATE = r"""
from manim import *
import wave
import numpy as np

class SoundWaveScene(Scene):
    def construct(self):
        # Audio file path injected via template
        audio_path = r"{audio_path}"
        
        # Read audio data
        try:
            with wave.open(audio_path, 'r') as wav_file:
                n_channels = wav_file.getnchannels()
                sampwidth = wav_file.getsampwidth()
                framerate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                
                # Read all frames
                raw_data = wav_file.readframes(n_frames)
                
                # Convert to numpy array
                dtype = np.int16 if sampwidth == 2 else np.uint8
                audio_data = np.frombuffer(raw_data, dtype=dtype)
                
                # If stereo, take only one channel (average or just left)
                if n_channels == 2:
                    audio_data = audio_data.reshape(-1, 2)
                    audio_data = audio_data.mean(axis=1)
                
                # Global normalization
                max_val = np.abs(audio_data).max()
                if max_val > 0:
                    audio_data = audio_data / max_val
                    
                duration = n_frames / framerate
                
        except Exception as e:
            print(f"Error reading audio: {{e}}")
            # Fallback to silence/flat line
            audio_data = np.zeros(100)
            duration = 5.0
            framerate = 44100

        # Visualization Config
        num_bars = 40
        bar_width = 0.2
        bar_spacing = 0.3
        
        # Create bars - use WHITE color for clean blending
        bars = VGroup(*[
            Rectangle(width=bar_width, height=0.1, fill_color=WHITE, fill_opacity=0.9, stroke_width=0)
            for _ in range(num_bars)
        ])
        bars.arrange(RIGHT, buff=bar_spacing - bar_width)
        bars.move_to(ORIGIN)
        
        self.add(bars)
        
        # Downsample audio to match frame rate updates (approx 60fps)
        # We need a function that returns the amplitude at time t
        
        def update_bars(bars, dt):
            # Current time in the animation
            # Scene time is tracked internally
            # We can use self.renderer.time roughly, but let's just use a value tracker if strictly needed.
            # However, standard updaters passed to 'always_redraw' or just 'add_updater' receive dt.
            # We need absolute time.
            pass

        # Better approach: 
        # Create a ValueTracker for time and animate it from 0 to duration
        time_tracker = ValueTracker(0)
        
        def get_amplitude_at_time(t):
            if t >= duration: return 0
            # Index in audio array
            index = int(t * framerate)
            if index >= len(audio_data): return 0
            
            # Get a window around this time to smooth it
            window_size = 1000 # Sample count window
            start = max(0, index - window_size // 2)
            end = min(len(audio_data), index + window_size // 2)
            
            chunk = audio_data[start:end]
            if len(chunk) == 0: return 0
            
            # RMS amplitude
            rms = np.sqrt(np.mean(chunk**2))
            return rms

        # Define updating function
        def update_wave(group):
            t = time_tracker.get_value()
            
            # Make the wave symmetrical
            # Center bars show current amplitude, outer bars show history/future or valid frequency bands?
            # Let's do a simple expanding wave or just randomized reaction to specific bands if we did FFT.
            # Since we only have raw amplitude: Let's make the center bars react to current volume
            # and outer bars decay.
            
            base_amp = get_amplitude_at_time(t)
            
            # Dynamic sensitivity
            sensitivity = 5.0
            
            for i, bar in enumerate(group):
                # Distance from center
                center_idx = num_bars / 2
                dist = abs(i - center_idx)
                
                # Offset time slightly for outer bars to create a "wave" effect outward?
                # or just scale amplitude by distance (Gaussian window)
                
                factor = np.exp(-0.1 * (dist**2)) # Gaussian falloff
                
                # Add some high-frequency noise simulation for visual interest
                # using sin waves based on index
                noise = 0.1 * np.sin(t * 10 + i)
                
                current_height = max(0.1, (base_amp * sensitivity * factor) + abs(noise))
                
                # Clamp height
                current_height = min(current_height, 4.0)
                
                # Manim bar update
                bar.generate_target()
                bar.target.stretch_to_fit_height(current_height)
                bar.target.move_to(bar.get_center()) # Keep center position? No, grow from center
                # actually stretch_to_fit_height creates a new height centered.
                
                # If we want to grow from center Y=0:
                bar.become(
                    Rectangle(
                        width=bar_width, 
                        height=current_height, 
                        fill_color=interpolate_color(WHITE, GRAY, base_amp), # White to gray based on loudness
                        fill_opacity=0.9, 
                        stroke_width=0
                    ).move_to(bar.get_center())
                )

        bars.add_updater(update_wave)
        
        # Play the animation for the duration of the audio
        # Use explicit keyword argument passing
        anim_duration = duration
        self.play(
            time_tracker.animate(run_time=anim_duration, rate_func=linear).set_value(duration)
        )
        
        bars.remove_updater(update_wave)

"""
