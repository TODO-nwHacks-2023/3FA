import React, { useCallback, useRef, useState } from "react";
import Measure from "react-measure";
import { useUserMedia } from "../functions/useUserMedia";
import styled, { css, keyframes } from "styled-components";
import { useOffsets } from "../hooks/useOffsets";
import WebCam from "react-webcam";
import { useCardRatio } from "../functions/useCardRatio";

// constrain the size of screenshot / video
const width = 600;
const height = width;

// component that renders the video feed
const WebCamCapture = () => {
  const webcamRef = useRef(null);
  const capture = useCallback(() => {
    const imageSrc = webcamRef.current.getScreenshot();
    // TODO imageSrc is a blob
  }, [webcamRef]);
  return (
    <>
      <WebCam
        audio={false}
        width={width}
        height={height}
        ref={webcamRef}
        screenshotFormat="image/jpeg"
        videoConstraints={CAPTURE_OPTIONS}
      />
      <button onClick={capture}>Capture photo</button>
    </>
  );
};
const CAPTURE_OPTIONS = {
  audio: false,
  width: width,
  height: height,
  video: { facingMode: "environment" },
};

export function Video({ setText, onCapture, onClear }) {
  const [container, setContainer] = useState({ width: 0, height: 0 });
  const videoRef = useRef();
  const canvasRef = useRef();
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);
  const [isCanvasEmpty, setIsCanvasEmpty] = useState(true);
  const [isFlashing, setIsFlashing] = useState(false);

  const mediaStream = useUserMedia(CAPTURE_OPTIONS, setText);
  const offsets = useOffsets(
    videoRef.current && videoRef.current.videoWidth,
    videoRef.current && videoRef.current.videoHeight,
    container.width,
    container.height
  );

  if (mediaStream && videoRef.current && !videoRef.current.srcObject) {
    videoRef.current.srcObject = mediaStream;
  }

  function handleResize(contentRect) {
    setContainer({
      width: contentRect.bounds.width,
      height: Math.round(contentRect.bounds.width / 1),
    });
  }

  function handleCapture() {
    const context = canvasRef.current.getContext("2d");

    context.drawImage(
      videoRef.current,
      offsets.x,
      offsets.y,
      container.width,
      container.height,
      0,
      0,
      container.width,
      container.height
    );

    canvasRef.current.toBlob((blob) => onCapture(blob), "image/jpeg", 1);
    setIsCanvasEmpty(false);
    setIsFlashing(true);
  }

  function handleClear() {
    const context = canvasRef.current.getContext("2d");
    context.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    setIsCanvasEmpty(true);
    onClear();
  }

  function handleCanPlay() {
    setIsVideoPlaying(true);
    videoRef.current.play();
  }

  return (
    <>
      {/* <WebCamCapture /> */}
      <Measure bounds onResize={handleResize}>
        {({ measureRef }) => (
          <>
            <Container
              ref={measureRef}
              maxHeight={videoRef.current && videoRef.current.videoHeight}
              maxWidth={videoRef.current && videoRef.current.videoWidth}
              style={{
                height: `${container.height}px`,
              }}>
              <VideoComponent
                ref={videoRef}
                onCanPlay={handleCanPlay}
                autoPlay
                playsInline
                muted
                style={{
                  top: `-${offsets.y}px`,
                  left: `-${offsets.x}px`,
                }}
              />
              <Canvas ref={canvasRef} width={container.width} height={container.height} />
              <Flash flash={isFlashing} onAnimationEnd={() => setIsFlashing(false)} />
            </Container>
            {isVideoPlaying && (
              <button onClick={isCanvasEmpty ? handleCapture : handleClear}>
                {isCanvasEmpty ? "Take a picture" : "Take another picture"}
              </button>
            )}
          </>
        )}
      </Measure>
    </>
  );
}

const Canvas = styled.canvas`
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  right: 0;
`;

const VideoComponent = styled.video`
  position: absolute;

  &::-webkit-media-controls-play-button {
    display: none !important;
    -webkit-appearance: none;
  }
`;

const Flash = styled.div`
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background-color: #ffffff;
  opacity: 0;

  ${({ flash }) => {
    if (flash) {
      return css`
        animation: ${flashAnimation} 750ms ease-out;
      `;
    }
  }}
`;

const Container = styled.div`
  position: relative;
  width: 100%;
  max-width: ${({ maxWidth }) => maxWidth && `${maxWidth}px`};
  max-height: ${({ maxHeight }) => maxHeight && `${maxHeight}px`};
  overflow: hidden;
`;

const flashAnimation = keyframes`
  from {
    opacity: 0.75;
  }

  to {
    opacity: 0;
  }
`;
