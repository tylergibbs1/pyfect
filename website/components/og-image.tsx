import { ImageResponse } from 'next/og';
import { logoSvg } from './logo';

// After fumadocs-ui's generateOGImage (MIT), whose fixed 82px title and 52px description
// overflowed the card once a title ran to three lines or a description to two: here the site's
// name comes first, the title shrinks as it grows, and the description stops at three lines.

const WIDTH = 1200;
const HEIGHT = 630;

/** The title's size: as large as fits in three lines of the card. */
function titleSize(title: string): number {
  if (title.length <= 28) return 76;
  if (title.length <= 56) return 64;
  return 54;
}

/** The site's 1200×630 Open Graph card: the logo and the site's name, a title and a description. */
export function ogImage({ title, description, site }: { title: string; description?: string; site: string }) {
  return new ImageResponse(
    (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          height: '100%',
          padding: '64px',
          gap: '28px',
          color: 'white',
          backgroundColor: '#0c0c0c',
          borderBottom: '18px solid rgba(250, 250, 250, 0.12)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', color: 'rgb(250, 250, 250)' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            width={44}
            height={44}
            alt=""
            src={`data:image/svg+xml;utf8,${encodeURIComponent(logoSvg('#fafafa'))}`}
          />
          <p style={{ fontSize: '40px', fontWeight: 600, margin: 0 }}>{site}</p>
        </div>
        <p style={{ fontSize: `${titleSize(title)}px`, fontWeight: 800, lineHeight: 1.12, margin: 0, marginTop: 'auto' }}>
          {title}
        </p>
        {description ? (
          <p
            style={{
              display: 'block',
              fontSize: '34px',
              lineHeight: 1.3,
              color: 'rgba(240, 240, 240, 0.75)',
              margin: 0,
              lineClamp: 3,
            }}
          >
            {description}
          </p>
        ) : null}
      </div>
    ),
    { width: WIDTH, height: HEIGHT },
  );
}
