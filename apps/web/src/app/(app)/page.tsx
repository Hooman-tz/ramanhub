import { Suspense } from "react";

import { FeedView } from "~/components/feed-view";

export default function HomePage() {
  // `FeedView` reads the search term from the URL (`?q=`), which the header's
  // search box sets — so it needs a Suspense boundary here.
  return (
    <Suspense fallback={null}>
      <FeedView showExpandedComposer />
    </Suspense>
  );
}
