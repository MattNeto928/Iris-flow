import os
from google import genai
from google.genai import types
from models import Segment, SegmentType


# Initialize client
client = genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))


TRANSITION_PROMPT = """You are a narrator for a Veritasium-style educational video. Generate a smooth, captivating transition that bridges two video segments.

**VERITASIUM STYLE:**
Write like Derek Muller speaks - conversational, intellectually curious, and with a sense of wonder. Your transitions should make viewers lean in, not zone out.

GLOBAL CONTEXT:
{context}

CONTEXT:
- Previous segment: {prev_title} ({prev_type})
  Description: {prev_description}
  Voiceover: {prev_voiceover}

- Next segment: {next_title} ({next_type})
  Description: {next_description}

**GUIDELINES:**
1. **Build Curiosity** - Make viewers want to see what's next
2. **Use Reveals** - "But here's where it gets really interesting..." or "And this is the part that surprised me..."
3. **Ask Questions** - "So what happens when we actually test this?" or "But does this really hold up?"
4. **Connect Emotionally** - Show genuine fascination, not just facts
5. **Keep it Natural** - Sound like you're talking to a curious friend
6. Length should be 1-3 sentences, appropriate for {transition_length} seconds of speech

**TRANSITION PHRASES TO USE:**
- "But here's where it gets really interesting..."
- "And this is the part that blew my mind..."
- "Now, you might think this is straightforward, but watch what happens..."
- "So I had to see this for myself..."
- "But there's something else going on here..."

**TRANSITION PHRASES TO AVOID:**
- "Let's visualize this..." (too formal)
- "Now we will see..." (passive, boring)
- "Moving on to..." (breaks immersion)

**TRANSITION STYLE BY TYPE:**
- To MANIM: "To really understand this, we need to look at the math..." or "Here's where the equation tells us something surprising..."
- To PYSIM: "But what does this actually look like in action?" or "Let's see what happens when we simulate this..."
- To ANIMATION: "Picture this..." or "Here's what's really happening..."

Generate ONLY the transition narration text, nothing else:
"""

CONCLUSION_PROMPT = """You are a narrator for a Veritasium-style educational video. Generate a compelling conclusion that wraps up the video.

**VERITASIUM STYLE:**
Conclusions should leave viewers with a sense of wonder, not just a summary. Connect back to the opening, express genuine gratitude, and leave a thought that lingers.

GLOBAL CONTEXT:
{context}

VIDEO SUMMARY:
{video_summary}

FIRST SEGMENT HOOK:
{opening_hook}

**GUIDELINES:**
1. **Summarize the Insight** - Not just facts, but the "aha" moment
2. **Connect to Opening** - Reference the initial hook or question
3. **Express Gratitude** - Genuine thanks, not formulaic
4. **Leave a Question** - Something for viewers to ponder
5. **Tease Curiosity** - "The next time you see X, you'll know..."
6. Length should be 3-5 sentences, appropriate for {conclusion_length} seconds of speech

**EXAMPLE CONCLUSIONS:**
- "And that's what makes [topic] so fascinating. It's not just about [surface understanding] - it's about [deeper insight]. The next time you [relevant action], you'll see it differently. Thanks for watching, and I'll see you in the next one."
- "So [topic] isn't what we thought it was. It's [new understanding]. I hope this changes how you think about [related concept]. Thanks for coming on this journey with me."

Generate ONLY the conclusion narration text, nothing else:
"""


async def generate_transition_text(
    from_segment: Segment,
    to_segment: Segment,
    target_seconds: float = 4.0,
    context: str = ""
) -> str:
    """
    Generate a brief narration that bridges two segments.
    
    Args:
        from_segment: The segment that just finished
        to_segment: The segment that's about to start
        target_seconds: Approximate length of transition in seconds
        
    Returns:
        Transition narration text
    """
    # Get voiceover text from previous segment if available
    prev_voiceover = ""
    if from_segment.voiceover and from_segment.voiceover.text:
        # Use full voiceover for context to avoid repetition
        prev_voiceover = from_segment.voiceover.text
    
    prompt = TRANSITION_PROMPT.format(
        prev_title=from_segment.title,
        prev_type=from_segment.type.value,
        prev_description=from_segment.description[:300],
        prev_voiceover=prev_voiceover,
        next_title=to_segment.title,
        next_type=to_segment.type.value,
        next_description=to_segment.description[:300],

        transition_length=target_seconds,
        context=context if context else "Educational video"
    )
    
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
        config={
            "temperature": 0.7,
            "max_output_tokens": 1024,
        }
    )
    
    transition_text = response.text.strip()
    
    # Clean up any quotes or extra formatting
    transition_text = transition_text.strip('"\'')
    
    print(f"[Transition] Generated: {transition_text}")
    return transition_text


async def generate_conclusion_text(
    segments: list,
    context: str = "",
    target_seconds: float = 8.0
) -> str:
    """
    Generate a Veritasium-style conclusion for the video.
    
    Args:
        segments: List of all segments in the video
        context: Overall video context/topic
        target_seconds: Approximate length of conclusion in seconds
        
    Returns:
        Conclusion narration text
    """
    # Get the opening hook from the first segment
    opening_hook = ""
    if segments and segments[0].voiceover and segments[0].voiceover.text:
        opening_hook = segments[0].voiceover.text[:200]
    
    # Build a summary of what was covered
    video_summary = ", ".join([s.title for s in segments if s.type != SegmentType.TRANSITION])
    
    prompt = CONCLUSION_PROMPT.format(
        context=context if context else "Educational video",
        video_summary=video_summary,
        opening_hook=opening_hook,
        conclusion_length=target_seconds
    )
    
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
        config={
            "temperature": 0.7,
            "max_output_tokens": 1024,
        }
    )
    
    conclusion_text = response.text.strip()
    conclusion_text = conclusion_text.strip('"\'')
    
    print(f"[Conclusion] Generated: {conclusion_text}")
    return conclusion_text


async def generate_segment_intro(
    segment: Segment,
    context: str = ""
) -> str:
    """
    Generate a Veritasium-style intro for a segment when there's no previous segment.
    
    Args:
        segment: The segment to introduce
        context: Optional context about the overall video
        
    Returns:
        Introduction narration text
    """
    intro_prompt = f"""You are a narrator for a Veritasium-style educational video. Generate a captivating introduction (2-3 sentences) for this opening segment.

**VERITASIUM STYLE:**
Open with a hook that creates intrigue - a surprising fact, a thought-provoking question, or an "imagine" scenario. Make viewers want to keep watching.

Segment: {segment.title}
Type: {segment.type.value}
Description: {segment.description[:300]}
Context: {context if context else "This is an educational video."}

**EXAMPLE HOOKS:**
- "Imagine a world where..."
- "What if I told you that..."
- "There's something deeply strange about X that most people never notice..."
- "Everyone thinks they understand X. But they're wrong."

Generate ONLY the intro text (no quotes, no explanations):
"""
    
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=intro_prompt,
        config={
            "temperature": 0.7,
            "max_output_tokens": 1024,
        }
    )
    
    return response.text.strip().strip('"\'')


def estimate_speech_duration(text: str, wpm: float = 150) -> float:
    """
    Estimate how long it takes to speak text.
    
    Args:
        text: The text to speak
        wpm: Words per minute (default 150, typical conversational pace)
        
    Returns:
        Estimated duration in seconds
    """
    word_count = len(text.split())
    return (word_count / wpm) * 60
