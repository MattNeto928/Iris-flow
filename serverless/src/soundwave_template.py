# Template for Manim Audio Visualization
SOUNDWAVE_TEMPLATE = r"""
from manim import *
import wave
import numpy as np

class SoundWaveScene(Scene):
    def construct(self):
        # Audio file path injected via template
        audio_path = r"{audio_path}"
        
        # Target vertical format
        self.camera.frame_width = 9
        self.camera.frame_height = 16
        
        # Read audio data
        try:
            with wave.open(audio_path, 'r') as wav_file:
                n_channels = wav_file.getnchannels()
                sampwidth = wav_file.getsampwidth()
                framerate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                
                raw_data = wav_file.readframes(n_frames)
                dtype = np.int16 if sampwidth == 2 else np.uint8
                audio_data = np.frombuffer(raw_data, dtype=dtype)
                
                if n_channels == 2:
                    audio_data = audio_data.reshape(-1, 2)
                    audio_data = audio_data.mean(axis=1)
                
                max_val = np.abs(audio_data).max()
                if max_val > 0:
                    audio_data = audio_data / max_val
                    
                duration = n_frames / framerate
                
        except Exception as e:
            print(f"Error reading audio: {{e}}")
            audio_data = np.zeros(100)
            duration = 5.0
            framerate = 44100

        # Visualization Config - vertical layout
        num_bars = 30
        bar_width = 0.15
        bar_spacing = 0.25
        
        bars = VGroup(*[
            Rectangle(width=bar_width, height=0.1, fill_color=WHITE, fill_opacity=0.9, stroke_width=0)
            for _ in range(num_bars)
        ])
        bars.arrange(RIGHT, buff=bar_spacing - bar_width)
        bars.move_to(ORIGIN)
        
        self.add(bars)
        
        time_tracker = ValueTracker(0)
        
        def get_amplitude_at_time(t):
            if t >= duration: return 0
            index = int(t * framerate)
            if index >= len(audio_data): return 0
            
            window_size = 1000
            start = max(0, index - window_size // 2)
            end = min(len(audio_data), index + window_size // 2)
            
            chunk = audio_data[start:end]
            if len(chunk) == 0: return 0
            
            rms = np.sqrt(np.mean(chunk**2))
            return rms

        def update_wave(group):
            t = time_tracker.get_value()
            base_amp = get_amplitude_at_time(t)
            sensitivity = 5.0
            
            for i, bar in enumerate(group):
                center_idx = num_bars / 2
                dist = abs(i - center_idx)
                factor = np.exp(-0.1 * (dist**2))
                noise = 0.1 * np.sin(t * 10 + i)
                current_height = max(0.1, (base_amp * sensitivity * factor) + abs(noise))
                current_height = min(current_height, 4.0)
                
                bar.become(
                    Rectangle(
                        width=bar_width, 
                        height=current_height, 
                        fill_color=interpolate_color(WHITE, GRAY, base_amp),
                        fill_opacity=0.9, 
                        stroke_width=0
                    ).move_to(bar.get_center())
                )

        bars.add_updater(update_wave)
        
        anim_duration = duration
        self.play(
            time_tracker.animate(run_time=anim_duration, rate_func=linear).set_value(duration)
        )
        
        bars.remove_updater(update_wave)
"""
