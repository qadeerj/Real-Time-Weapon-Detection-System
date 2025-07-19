document.addEventListener('DOMContentLoaded', () => {
  const btnLive = document.getElementById('btn-live');
  const btnStop = document.getElementById('btn-stop');
  const uploadForm = document.getElementById('upload-form');
  const uploadLoadingBar = document.getElementById('upload-loading-bar');
  const uploadProgressText = document.getElementById('upload-progress-text');
  const uploadBtn = uploadForm ? uploadForm.querySelector('button[type="submit"]') : null;
  const videoStream = document.getElementById('video-stream');
  const animatedImg = document.getElementById('animated-img');
  const videoFeedImg = document.getElementById('video-feed-img');
  const btnStopHeader = document.getElementById('btn-stop-header');

  // Always clear video feed src on page load for safety
  if (videoFeedImg) videoFeedImg.src = '';

  // Initial state: only Start Detection, static image, and upload form are visible
  if (videoStream) videoStream.style.display = 'none';
  if (animatedImg) animatedImg.style.display = 'block';
  if (uploadForm) uploadForm.style.display = 'block';
  if (btnLive) btnLive.style.display = 'block';
  if (btnStop) btnStop.style.display = 'none';
  if (videoFeedImg) videoFeedImg.src = '';
  if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
  if (uploadProgressText) uploadProgressText.style.display = 'none';

  // Upload form loading bar and percent logic
  if (uploadForm) {
    uploadForm.addEventListener('submit', function(e) {
      // Use AJAX upload for progress
      if (window.XMLHttpRequest && window.FormData) {
        e.preventDefault();
        if (uploadLoadingBar) {
          uploadLoadingBar.style.display = 'block';
          uploadLoadingBar.style.width = '0%';
        }
        if (uploadProgressText) {
          uploadProgressText.style.display = 'inline';
          uploadProgressText.textContent = '0% video processed';
        }
        if (uploadBtn) uploadBtn.disabled = true;
        const formData = new FormData(uploadForm);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', uploadForm.action, true);
        xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        xhr.upload.onprogress = function(e) {
          if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            if (uploadLoadingBar) uploadLoadingBar.style.width = percent + '%';
            if (uploadProgressText) uploadProgressText.textContent = 'Video under processing...';
          }
        };
        xhr.onload = function() {
          // After upload, start polling for processing progress
          let job_id = null;
          try {
            const resp = JSON.parse(xhr.responseText);
            job_id = resp.job_id;
          } catch (e) {}
          if (!job_id) {
            if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
            if (uploadProgressText) uploadProgressText.style.display = 'none';
            if (uploadBtn) uploadBtn.disabled = false;
            alert('Upload failed. Please try again.');
            return;
          }
          // Start polling for processing progress
          if (uploadProgressText) uploadProgressText.textContent = '0% video processed';
          let lastPercent = 0;
          const poll = setInterval(() => {
            fetch('/api/video_progress?job_id=' + job_id)
              .then(res => res.json())
              .then(data => {
                const percent = data.percent || 0;
                if (uploadLoadingBar) uploadLoadingBar.style.width = percent + '%';
                if (uploadProgressText) uploadProgressText.textContent = 'Video under processing...';
                lastPercent = percent;
                if (percent >= 100) {
                  clearInterval(poll);
                  setTimeout(() => {
                    if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
                    if (uploadProgressText) uploadProgressText.style.display = 'none';
                    if (uploadBtn) uploadBtn.disabled = false;
                    window.location.reload();
                  }, 5000);
                }
              })
              .catch(() => {
                clearInterval(poll);
                if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
                if (uploadProgressText) uploadProgressText.style.display = 'none';
                if (uploadBtn) uploadBtn.disabled = false;
                alert('Processing failed. Please try again.');
              });
          }, 2000);
        };
        xhr.onerror = function() {
          if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
          if (uploadProgressText) uploadProgressText.style.display = 'none';
          if (uploadBtn) uploadBtn.disabled = false;
          alert('Upload failed. Please try again.');
        };
        xhr.send(formData);
      } else {
        // Fallback: normal submit
        if (uploadLoadingBar) uploadLoadingBar.style.display = 'block';
        if (uploadBtn) uploadBtn.disabled = true;
      }
    });
  }
  window.addEventListener('pageshow', function() {
    if (uploadLoadingBar) uploadLoadingBar.style.display = 'none';
    if (uploadProgressText) uploadProgressText.style.display = 'none';
    if (uploadBtn) uploadBtn.disabled = false;
  });


  // Camera names for each grid position (1-20)
  const cameraNames = [
    'Front Door', 'Back Door', 'Garage', 'Living Room', 'Driveway',
    'Office', 'Kitchen', 'Hallway', 'Porch', 'Yard',
    'Gate', 'Parking', 'Lobby', 'Stairs', 'Elevator',
    'Warehouse', 'Shop', 'Server Room', 'Rooftop', 'Basement'
  ];
  // Only use cameraUrls for stream and popup
  const cameraUrls = [
    0, null, null, null, null,
    null, null, null, null, null,
    null, null, null, null, null,
    null, null, null, null, null // Only last slot is webcam
  ];

  function startAllCameras() {
    for (let i = 0; i < 20; i++) {
      const url = cameraUrls[i];
      const img = document.getElementById('video-feed-img-' + (i + 1));
      const placeholder = document.getElementById('placeholder' + (i + 1));
      if (url !== null && img) {
        if (typeof url === 'string' && (url.startsWith('rtsp://') || url.startsWith('http://') || url.startsWith('https://'))) {
          img.src = '/video_feed?url=' + encodeURIComponent(url);
        } else {
          img.src = '/video_feed?cam=' + url;
        }
        img.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
      } else {
        if (img) {
          img.src = '';
          img.style.display = 'none';
        }
        if (placeholder) placeholder.style.display = 'flex';
      }
    }
  }

  function stopAllCameras() {
    for (let i = 0; i < 24; i++) {
      const url = cameraUrls[i];
      const img = document.getElementById('video-feed-img-' + (i + 1));
      const placeholder = document.getElementById('placeholder' + (i + 1));
      if (img) {
        // Only call stop_video for valid camera index/url
        if (url !== null && url !== undefined && url !== '') {
          fetch('/stop_video?cam=' + url);
        }
        img.src = '';
        img.style.display = 'none';
      }
      if (placeholder) placeholder.style.display = 'flex';
    }
  }

  // Highlight camera cell for 10 seconds
  function highlightCamera(index) {
    // Show popup notification for detection
    const popup = document.getElementById('detection-popup');
    const name = cameraNames[index - 1] || `Camera ${index}`;
    const url = cameraUrls[index - 1];
    let popupContent = `Detection on <b>${name}</b>`;
    if (typeof url === 'string' && (url.startsWith('rtsp://') || url.startsWith('http://') || url.startsWith('https://'))) {
      popupContent += `<br><a href='${url}' target='_blank' style='color:#fff;text-decoration:underline;font-size:1.1rem;'>View Stream</a>`;
    }
    if (popup) {
      popup.innerHTML = popupContent;
      popup.style.display = 'block';
      clearTimeout(popup._timeout);
      popup._timeout = setTimeout(() => {
        popup.style.display = 'none';
      }, 5000);
    }
    playAlertSound();
  }

  // Remove highlight from all cameras
  function removeAllHighlights() {
    for (let i = 1; i <= 24; i++) {
      const cell = document.getElementById('cam-cell-' + i);
      if (cell) cell.classList.remove('highlighted');
    }
  }

  // Stop everything on navigation as well
  function stopEverything() {
    stopAllCameras();
    stopHighlightPoll();
    removeAllHighlights();
  }

  // Poll backend for detection highlight
  let highlightPoll = null;
  function startHighlightPoll() {
    if (highlightPoll) return;
    highlightPoll = setInterval(function() {
      fetch('/api/trigger_highlight')
        .then(res => res.json())
        .then(data => {
          if (data.cameras && Array.isArray(data.cameras)) {
            data.cameras.forEach(idx => highlightCamera(idx));
          } else if (data.camera) {
            highlightCamera(data.camera);
          }
        });
    }, 2000);
  }
  function stopHighlightPoll() {
    if (highlightPoll) {
      clearInterval(highlightPoll);
      highlightPoll = null;
    }
    removeAllHighlights();
  }

  // Unlock audio on first user interaction
  let audioUnlocked = false;
  function unlockAlertAudio() {
    if (audioUnlocked) return;
    const audio = document.getElementById('alert-audio');
    if (audio) {
      audio.volume = 0;
      audio.play().then(() => {
        audio.pause();
        audio.currentTime = 0;
        audio.volume = 1;
        audioUnlocked = true;
      }).catch(() => {});
    }
  }
  if (btnLive) {
    btnLive.addEventListener('click', function() {
      unlockAlertAudio();
    });
  }

  btnLive.addEventListener('click', () => {
    if (uploadForm) uploadForm.style.display = 'none';
    if (animatedImg) animatedImg.style.display = 'none';
    if (videoStream) videoStream.style.display = 'block';
    startAllCameras();
    startHighlightPoll();
    if (btnLive) btnLive.style.display = 'none';
    if (btnStop) btnStop.style.display = 'block';
  });

  btnStop.addEventListener('click', () => {
    stopEverything();
    if (videoStream) videoStream.style.display = 'none';
    if (animatedImg) animatedImg.style.display = 'block';
    if (uploadForm) uploadForm.style.display = 'block';
    if (btnLive) btnLive.style.display = 'block';
    if (btnStop) btnStop.style.display = 'none';
  });

  if (btnStopHeader) {
    btnStopHeader.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      stopEverything();
      if (videoStream) videoStream.style.display = 'none';
      if (animatedImg) animatedImg.style.display = 'block';
      if (uploadForm) uploadForm.style.display = 'block';
      if (btnLive) btnLive.style.display = 'block';
      if (btnStop) btnStop.style.display = 'none';
      // Optionally hide the live header
      const liveHeader = document.getElementById('live-header');
      if (liveHeader) liveHeader.style.display = 'none';
      const defaultHeader = document.querySelector('body > header');
      if (defaultHeader) defaultHeader.style.display = 'block';
    });
  }

  // Ensure camera stops on navigation (header links)
  function stopCameraOnNav(e) {
    stopEverything();
  }
  document.querySelectorAll('.back-home-btn, .history-link').forEach(link => {
    link.addEventListener('click', stopCameraOnNav);
  });

  // Ensure camera stops on page unload/close
  window.addEventListener('beforeunload', function() {
    stopEverything();
    navigator.sendBeacon && navigator.sendBeacon('/stop_video');
    // fallback for browsers without sendBeacon
    if (!navigator.sendBeacon) fetch('/stop_video', {method:'POST', keepalive:true});
  });
});

// Play alert sound for 10 seconds
function playAlertSound() {
  const audio = document.getElementById('alert-audio');
  if (audio) {
    audio.src = '/static/Alert/alert-33762.mp3';
    audio.currentTime = 0;
    audio.play();
  }
}
