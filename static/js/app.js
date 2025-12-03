// Main client-side JS for index.html
// Handles stream fallback, recording, and loading grouped videos

// Stream fallback handling
(function(){
  const img = document.getElementById('mjpeg');
  const iframe = document.getElementById('mjpeg_iframe');
  const status = document.getElementById('status');

  function showStreaming() {
    if (status) status.textContent = 'Streaming';
    img.style.display = '';
    iframe.style.display = 'none';
  }

  function showFallback() {
    if (status) status.textContent = 'Using iframe fallback';
    img.style.display = 'none';
    iframe.style.display = 'block';
  }

  img.addEventListener('load', function(){ showStreaming(); });
  img.addEventListener('error', function(){ showFallback(); });

  setTimeout(function(){
    if (img.complete === false) {
      showFallback();
    }
  }, 4000);
})();

// Recording UI
(function(){
  const btn = document.getElementById('recordBtn');
  const status = document.getElementById('recordStatus');
  const linkBox = document.getElementById('recordingLink');

  async function startRecord(){
    status.textContent = 'Starting...';
    btn.disabled = true;
    linkBox.innerHTML = '';
    try{
      const resp = await fetch('/record', { method: 'POST' });
      if (!resp.ok) throw new Error('busy');
      const data = await resp.json();
      status.textContent = `Recording ${data.duration}s...`;
      setTimeout(async ()=>{
        status.textContent = 'Finalizing...';
        const r = await fetch('/last_recording');
        const j = await r.json();
        if (j.filename){
          const a = document.createElement('a');
          a.href = '/recordings/' + encodeURIComponent(j.filename);
          a.textContent = 'Download: ' + j.filename;
          linkBox.appendChild(a);
          status.textContent = 'Recording ready';
        } else {
          status.textContent = 'No recording found';
        }
        btn.disabled = false;
      }, (10 + 1) * 1000);
    }catch(e){
      status.textContent = 'Recorder busy';
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', startRecord);
})();

// Video list UI (grouped by date)
(function(){
  const videoList = document.getElementById('videoList');

  async function loadVideos(){
    videoList.innerHTML = '<p style="color:#888;">Loading videos...</p>';
    try{
      const resp = await fetch('/videos/grouped');
      if (!resp.ok) throw new Error('Failed to fetch');
      const groups = await resp.json();

      if (!Array.isArray(groups) || groups.length === 0){
        videoList.innerHTML = '<p style="color:#888;">No videos yet</p>';
        return;
      }

      let html = '';
      groups.forEach(group => {
        const dateLabel = group.date === 'unknown' ? 'Unknown date' : new Date(group.date).toLocaleDateString();
        const count = Array.isArray(group.videos) ? group.videos.length : 0;
        const plural = count === 1 ? 'video' : 'videos';
        html += `<div style="margin-bottom:12px;">
          <button class="date-btn" aria-expanded="false">${dateLabel} (${count} ${plural})</button>
            <div class="group-videos" style="display:none;">
              <ul style="list-style:none;padding:0;margin:8px 0 0 0;">
        `;

        group.videos.forEach(v => {
          const date = v.created_at ? new Date(v.created_at).toLocaleString() : '';
          const size = v.size ? (v.size / (1024*1024)).toFixed(2) : '0.00';
          const streamUrl = (v.url && v.url.startsWith('http')) ? v.url : (`/recordings/${encodeURIComponent(v.filename)}`);
            html += `
                <li class="video-entry">
                  <div><strong>${v.filename}</strong></div>
                  <div style="font-size:0.9em;color:#aaa;">${date} • ${size} MB</div>
                  <div style="margin-top:8px;">
                    <a href="${streamUrl}" target="_blank" style="color:#0088ff;margin-right:12px;">Stream</a>
                    <a href="${streamUrl}" download="${v.filename}" style="color:#0088ff;">Download</a>
                  </div>
                </li>
          `;
        });

        html += '</ul></div></div>';
      });

      videoList.innerHTML = html;

      document.querySelectorAll('#videoList .date-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const list = btn.nextElementSibling;
          if (!list) return;
          const isHidden = list.style.display === 'none' || list.style.display === '';
          list.style.display = isHidden ? 'block' : 'none';
          btn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        });
      });

    }catch(e){
      videoList.innerHTML = '<p style="color:#f55;">Failed to load videos</p>';
      console.error(e);
    }
  }

  // Load videos once on page load. Removed manual refresh button and auto-refresh.
  loadVideos();
})();
