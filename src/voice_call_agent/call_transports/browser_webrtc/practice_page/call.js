"use strict";

// One practice call: a WebRTC peer connection to the agent, negotiated with a single offer and
// answer once every ICE candidate is gathered (no trickle ICE).

const OFFER_PATH = "/practice/offer";
const LINES_PATH = "/practice/lines";
const KEEP_ALIVE_INTERVAL_MS = 1000;

let peer = null;
let microphone = null;
let keepAlive = null;

function showStatus(text) {
  document.getElementById("call-status").textContent = text;
}

function showCallControls(inCall) {
  document.getElementById("start-call").disabled = inCall;
  document.getElementById("hang-up").disabled = !inCall;
  document.getElementById("practice-line").disabled = inCall;
}

// Each practice line reaches one business, as a phone line's dialed number does. Without lines
// (no practice schedule), the call dials none and the backend decides.
async function showPracticeLines() {
  const response = await fetch(LINES_PATH);
  if (!response.ok) {
    throw new Error(`the service did not list its lines (HTTP ${response.status})`);
  }
  const lines = await response.json();
  const choice = document.getElementById("practice-line");
  for (const line of lines) {
    choice.append(new Option(`${line.business_name} (${line.number})`, line.number));
  }
  document.getElementById("line-choice").hidden = lines.length === 0;
}

function dialedNumber() {
  const choice = document.getElementById("practice-line");
  return choice.value === "" ? null : choice.value;
}

function iceGatheringComplete(connection) {
  if (connection.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    connection.addEventListener("icegatheringstatechange", () => {
      if (connection.iceGatheringState === "complete") {
        resolve();
      }
    });
  });
}

// Pipecat's SmallWebRTC connection reads these pings to know the browser is still there.
function startKeepAlive(connection) {
  const channel = connection.createDataChannel("keep-alive");
  channel.addEventListener("open", () => {
    keepAlive = setInterval(() => channel.send("ping"), KEEP_ALIVE_INTERVAL_MS);
  });
}

async function startCall() {
  showCallControls(true);
  showStatus("Asking for the microphone...");
  microphone = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const connection = new RTCPeerConnection();
  peer = connection;
  connection.addTransceiver(microphone.getAudioTracks()[0], {
    direction: "sendrecv",
    streams: [microphone],
  });
  startKeepAlive(connection);
  connection.addEventListener("track", (event) => {
    document.getElementById("agent-voice").srcObject = new MediaStream([event.track]);
  });
  connection.addEventListener("connectionstatechange", () => {
    showStatus(`Connection: ${connection.connectionState}.`);
    if (connection.connectionState === "failed") {
      hangUp("The connection failed.");
    }
  });
  showStatus("Connecting...");
  await connection.setLocalDescription(await connection.createOffer());
  await iceGatheringComplete(connection);
  const offer = connection.localDescription;
  const response = await fetch(OFFER_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sdp: offer.sdp, type: offer.type, dialed_number: dialedNumber() }),
  });
  if (!response.ok) {
    throw new Error(`the service refused the call (HTTP ${response.status})`);
  }
  await connection.setRemoteDescription(await response.json());
}

function hangUp(reason) {
  clearInterval(keepAlive);
  keepAlive = null;
  if (peer !== null) {
    peer.close();
    peer = null;
  }
  if (microphone !== null) {
    microphone.getTracks().forEach((track) => track.stop());
    microphone = null;
  }
  showCallControls(false);
  showStatus(reason);
}

document.getElementById("start-call").addEventListener("click", () => {
  startCall().catch((error) => hangUp(`Could not start the call: ${error.message}`));
});
document.getElementById("hang-up").addEventListener("click", () => hangUp("Call ended."));
window.addEventListener("pagehide", () => hangUp("Call ended."));
showPracticeLines().catch((error) => showStatus(`Could not list the lines: ${error.message}`));
