import { api } from "../api";
import { Card, ErrorBox, Loading, go, useAsync } from "../ui";
import { IdentityBody } from "./Identity";

export function MyAccessView() {
  const { data, error, loading, reload } = useAsync(() => api.myAccess(), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  if (!data.in_inventory || !data.id) {
    return (
      <Card title="Você ainda não aparece no inventário" subtitle={data.email}>
        <p className="text-sm text-text-dim">
          O inventário cobre os grupos e catalogs do escopo do modelo. Se você não faz parte de nenhum grupo do escopo,
          não há acesso a mostrar aqui. Você pode <button className="text-lava hover:underline" onClick={() => go("requests", "new")}>pedir acesso</button>.
        </p>
      </Card>
    );
  }
  return <IdentityBody d={data} id={data.id} embedded />;
}
