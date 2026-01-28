import boto3
import json

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/482625028438/iris-flow-topic-queue"
sqs = boto3.client('sqs', region_name='us-east-1')

topics = [
    # MEMS (Micro-Electro-Mechanical Systems)
    "Explain how MEMS accelerometers in smartphones detect motion and orientation",
    "How Digital Micromirror Devices (DLP) work in projectors using millions of tiny mirrors",
    "The physics of MEMS gyroscopes: Measuring rotation with vibrating structures",
    "MEMS microphones: How silicon chips capture high-fidelity audio",
    "RF MEMS switches: Miniature mechanical relays for 5G and radar",
    "Lab-on-a-chip: Microfluidics and MEMS for medical diagnostics",
    "MEMS pressure sensors: From tire pressure monitoring to altimeters",
    "Piezoelectric MEMS energy harvesters: Powering sensors from vibration",
    "Optical MEMS: Scanning micromirrors for LIDAR and barcode readers",
    
    # Nanophotonics & Optics
    "Photonic crystals: Creating bandgaps for light to control data at the speed of light",
    "Metamaterials and invisibility cloaks: Bending light around objects",
    "Surface Plasmon Resonance: How light interacts with metal surfaces at the nanoscale",
    "Optical tweezers: Using lasers to trap and move individual cells and atoms",
    "Silicon photonics: Integrating lasers and optics directly onto computer chips",
    "Quantum dots: Nanoscale semiconductors creating vibrant colors in displays",
    "Structural coloration: How butterfly wings create color without pigment using nanostructures",
    "Near-field scanning optical microscopy (NSOM): Breaking the diffraction limit",
    "Plasmonic computing: Combining the size of electronics with the speed of photonics",

    # Quantum Theory & Physics
    "Quantum entanglement: The spooky action at a distance that Einstein couldn't accept",
    "The Double Slit Experiment: How particles behave as waves",
    "Quantum tunneling: The bizarre phenomenon that lets particles pass through barriers",
    "Schrödinger's Cat: Exploring the concept of quantum superposition",
    "The Uncertainty Principle: Why we can't know position and momentum simultaneously",
    "Quantum Teleportation: Transferring quantum states across distances",
    "The Bloch Sphere: Visualizing Qubits and quantum states",
    "Quantum Key Distribution (BB84 Protocol): Unbreakable encryption using physics",
    "Bell's Theorem: Proving that the universe is not locally real",
    "Quantum Eraser Experiment: Changing the past with future measurements?",
    "Wave-particle duality: Is light a particle or a wave?",
    "Superconductivity: Quantum mechanics on a macroscopic scale",
    "Quantum Zeno Effect: Freezing a system by observing it"
]

print(f"Adding {len(topics)} topics to queue: {QUEUE_URL}")

for topic in topics:
    response = sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({"topic": topic})
    )
    print(f"Sent: {topic[:50]}... (ID: {response['MessageId']})")

print("Done!")
