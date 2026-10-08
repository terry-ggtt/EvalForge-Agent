interface PlaceholderPageProps {
  title: string;

  description: string;
}


export function PlaceholderPage(
  {
    title,
    description,
  }: PlaceholderPageProps
) {

  return (
    <div>

      <h2
        className="
          text-2xl
          font-semibold
        "
      >
        {title}
      </h2>


      <p
        className="
          mt-2
          text-sm
          text-slate-500
        "
      >
        {description}
      </p>


      <div
        className="
          mt-6
          rounded-xl
          border
          border-dashed
          border-slate-300
          bg-white
          p-8
          text-sm
          text-slate-500
        "
      >
        This page will be implemented later.
      </div>

    </div>
  );
}