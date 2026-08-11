# tiktok-ui Specification

## Purpose
Responsive web UI for browsing TikTok download history and initiating
downloads with intuitive controls.

## Requirements

### Requirement: Download Input
The UI MUST include an input field for TikTok username or URL and a download button.

#### Scenario: Initiate Download
- GIVEN a user enters a TikTok username in the input field
- WHEN the user clicks "Download"
- THEN a progress indicator is shown
- AND the download job is started via the API

### Requirement: History View with Thumbnails
The UI MUST display a history view showing downloaded videos with metadata.

#### Scenario: Browse History
- GIVEN multiple videos have been downloaded
- WHEN the user navigates to the History view
- THEN each video appears with title, username, and download date
- AND the list is paginated

### Requirement: Settings Panel
The UI MUST provide a settings panel for proxy, cookies, and video format.

#### Scenario: Configure Proxy and Cookies
- GIVEN the user opens Settings
- WHEN they set the proxy URL and upload a cookies file
- THEN the UI stores these preferences
- AND subsequent downloads use the configured settings

### Requirement: Responsive Design
The UI MUST be functional on both desktop and mobile devices.

#### Scenario: Mobile Usage
- GIVEN a user on a mobile device
- WHEN they access the UI
- THEN the layout adapts to the screen size
- AND all controls remain usable and accessible