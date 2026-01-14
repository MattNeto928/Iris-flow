import os
import json
from google import genai
from typing import List
from models import Segment, SegmentType, VoiceoverConfig


# Initialize client
client = genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))


SEGMENT_GENERATION_PROMPT = """You are a video production assistant creating Veritasium-style educational content. Given a user's prompt, break it down into a sequence of compelling video segments.

**VERITASIUM STYLE GUIDE:**
Your videos should feel like a Veritasium documentary - intellectually captivating, conversational yet authoritative, and structured to hook viewers from the first second. The tone should make complex topics feel accessible while respecting the viewer's intelligence.

**KEY PRINCIPLES:**
1. **HOOK FIRST** - Open with a mind-bending question, paradox, or visually stunning simulation
2. **PYSIM OPENING** - Prefer starting with a "pysim" segment for immediate visual engagement
3. **CONVERSATIONAL AUTHORITY** - Write like you're explaining to a curious friend, not lecturing
4. **BUILD MYSTERY** - Each section should raise questions before answering them
5. **END WITH WONDER** - Conclude with gratitude and a lingering thought

**SEGMENT TYPES:**
1. "pysim" - Scientific simulations, physics demos, particle systems (PREFERRED for opening hooks)
2. "animation" - Creative visuals, stock-like footage (uses Gemini Veo 3.1)
3. "manim" - Mathematical visualizations, equations, graphs, proofs (uses Manim library)
4. "transition" - Black screen bridges OR conclusion segments to connect/close ideas

**VIDEO STRUCTURE:**
- **OPENING:** Start with a pysim simulation + hook narration like:
  * "Imagine a place where the laws of physics are pushed to their absolute breaking point..."
  * "What if I told you that everything you think you know about X is wrong?"
  * "There's something deeply strange about X that most people never notice..."
- **MIDDLE:** Alternate between visual segments and transition bridges
- **CLOSING:** End with a "transition" segment that serves as the conclusion:
  * Summarize the key insight (the "aha" moment, not just facts)
  * Express genuine gratitude: "Thanks for watching" or "I hope you found this fascinating"
  * Leave a lingering question or thought to ponder

**SEGMENT FLOW RULES:**
- **ALWAYS** insert a "transition" segment between different content blocks
- Transition voiceovers should build curiosity: "But here's where it gets really interesting..." or "And this is the part that blew my mind..."
- Content segment voiceovers focus **ONLY** on what's visible on screen
- The FINAL segment should be a "transition" type serving as the conclusion

For each segment, provide:
- order: The sequence number (starting from 0)
- type: One of "animation", "manim", "pysim", or "transition"
- title: A short title for the segment
- description: 
  * For content types: Detailed description of what should be shown visually.
  * For "transition": "Black screen" (the visuals will be blank).
- voiceover: Object with "text" field containing the Veritasium-style narration.
- metadata: Any additional parameters. For final segments, add {"is_conclusion": true}

Respond with a JSON object containing a "segments" array.

Example response (for "Explain black holes"):
{
  "segments": [
    {
      "order": 0,
      "type": "pysim",
      "title": "Black Hole Visualization",
      "description": "A stunning particle simulation showing matter spiraling into a black hole's event horizon, with gravitational lensing effects distorting the background stars",
      "voiceover": {"text": "Imagine a place where the laws of physics are pushed to their absolute breaking point. A place so dense that not even light can escape its grasp. Today, we're exploring the most mysterious objects in the universe: black holes."},
      "metadata": {"style": "dramatic"}
    },
    {
      "order": 1,
      "type": "transition",
      "title": "Setting Up the Physics",
      "description": "Black screen",
      "voiceover": {"text": "But here's the thing that really blew my mind when I first learned about this. To understand what makes black holes so special, we need to look at how gravity bends the very fabric of space itself."},
      "metadata": {}
    },
    {
      "order": 2,
      "type": "manim",
      "title": "Schwarzschild Radius",
      "description": "Animate the Schwarzschild radius equation r_s = 2GM/c², showing how mass determines the event horizon size",
      "voiceover": {"text": "This is the Schwarzschild radius - the point of no return. Once anything crosses this boundary, its fate is sealed."},
      "metadata": {}
    },
    {
      "order": 3,
      "type": "transition",
      "title": "Conclusion",
      "description": "Black screen",
      "voiceover": {"text": "And that's what makes black holes so fascinating. They're not just cosmic vacuum cleaners - they're windows into the extreme limits of physics itself. The next time you look up at the night sky, remember: there are millions of these invisible giants out there, warping the universe around them. Thanks for watching, and I'll see you in the next one."},
      "metadata": {"is_conclusion": true}
    }
  ]
}

User's prompt:
"""


async def generate_segments_from_prompt(prompt: str, default_voice: str = "Fenrir", default_speed: float = 1.15) -> List[Segment]:
    """
    Use Gemini to parse a user prompt into structured video segments.
    """
    full_prompt = SEGMENT_GENERATION_PROMPT + prompt

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=full_prompt,
        config={
            "temperature": 0.7,
            "top_p": 0.95,
            "max_output_tokens": 16384,
            "response_mime_type": "application/json",
        }
    )
    
    # Parse the JSON response
    try:
        result = json.loads(response.text)
        segments_data = result.get("segments", [])
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        text = response.text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            result = json.loads(text[start:end])
            segments_data = result.get("segments", [])
        else:
            raise ValueError("Failed to parse Gemini response as JSON")

    # Convert to Segment objects
    segments = []
    for seg_data in segments_data:
        voiceover = None
        if seg_data.get("voiceover"):
            vo_data = seg_data["voiceover"]
            if isinstance(vo_data, dict) and vo_data.get("text"):
                voiceover = VoiceoverConfig(
                    text=vo_data["text"],
                    voice=vo_data.get("voice", default_voice),
                    speed=vo_data.get("speed", default_speed)
                )

        segment = Segment(
            order=seg_data.get("order", len(segments)),
            type=SegmentType(seg_data["type"]),
            title=seg_data.get("title", f"Segment {len(segments) + 1}"),
            description=seg_data.get("description", ""),
            voiceover=voiceover,
            metadata=seg_data.get("metadata", {})
        )
        segments.append(segment)

    return segments
