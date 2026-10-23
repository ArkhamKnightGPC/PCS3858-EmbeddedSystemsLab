const horizonLayer = document.getElementById("horizon-sky-ground");
const pitchVal = document.getElementById("pitch-val");
const rollVal = document.getElementById("roll-val");
const gVal = document.getElementById("g-val");

if (telemetry.mpu_valid) {
    const pitch = telemetry.pitch_deg ?? 0;
    const roll = telemetry.roll_deg ?? 0;

    pitchVal.innerText = pitch.toFixed(1);
    rollVal.innerText = roll.toFixed(1);
    gVal.innerText = (telemetry.accel_magnitude ?? 0).toFixed(2);

    // Translate pitch (2px per degree) and rotate roll
    const pitchOffset = pitch * 2; 
    horizonLayer.style.transform = `translateY(${pitchOffset}px) rotate(${-roll}deg)`;
} else {
    pitchVal.innerText = "--";
    rollVal.innerText = "--";
    gVal.innerText = "--";
}